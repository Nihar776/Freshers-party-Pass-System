"""
roster_routes.py
Admin-only: bulk-import the existing student roster (before any sales
happen), and list/search it. Wire into main.py with
app.include_router(roster_router).

CSV columns required: sap_id,name,branch
Optional columns: gender,email
"""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from schema_v2 import Student, User, UserRole, PaymentStatus
from session_auth import require_role
from audit import write_audit_log

router = APIRouter(prefix="/admin/roster", tags=["roster"])

REQUIRED_COLUMNS = {"sap_id", "name", "branch", "year"}


class RosterImportResult(BaseModel):
    created: int
    skipped_duplicates: list[str]
    row_errors: list[str]


class StudentSummary(BaseModel):
    id: int
    sap_id: str
    name: str
    branch: str
    gender: Optional[str]
    payment_status: PaymentStatus

    class Config:
        from_attributes = True


@router.post("/import", response_model=RosterImportResult)
def import_roster(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
):
    try:
        filename = file.filename or "unknown.csv"
        if not filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Please upload a .csv file")

        try:
            raw = file.file.read().decode("utf-8-sig")  # utf-8-sig strips a stray BOM from Excel exports
            reader = csv.DictReader(io.StringIO(raw))
            if reader.fieldnames:
                reader.fieldnames = [c.strip() for c in reader.fieldnames]
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Invalid file encoding. Please ensure the file is a valid CSV (not an Excel .xlsx file) and saved with UTF-8 encoding.")

        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
            raise HTTPException(
                status_code=400,
                detail=f"CSV must have columns: {sorted(REQUIRED_COLUMNS)}. Found: {reader.fieldnames}",
            )

        created = 0
        skipped_duplicates: list[str] = []
        row_errors: list[str] = []
        seen_in_file: set[str] = set()  # catch duplicate SAP IDs within the uploaded file itself

        for line_num, row in enumerate(reader, start=2):  # header is line 1
            sap_id = (row.get("sap_id") or "").strip()
            name = (row.get("name") or "").strip()
            branch = (row.get("branch") or "").strip()
            year = (row.get("year") or "").strip() or None
            gender = (row.get("gender") or "").strip() or None
            email = (row.get("email") or "").strip() or None

            if not sap_id or not name or not branch or not year:
                row_errors.append(f"Line {line_num}: missing sap_id/name/branch/year, skipped")
                continue

            if year not in {"FY", "SY", "TY", "LY"}:
                row_errors.append(f"Line {line_num}: invalid year '{year}' (must be FY, SY, TY, or LY), skipped")
                continue

            if sap_id in seen_in_file:
                row_errors.append(f"Line {line_num}: duplicate SAP ID '{sap_id}' within this file, skipped")
                continue
            seen_in_file.add(sap_id)

            existing = db.query(Student).filter(Student.sap_id == sap_id).first()
            if existing:
                skipped_duplicates.append(sap_id)
                continue

            student = Student(sap_id=sap_id, name=name, branch=branch, year=year, gender=gender, email=email)
            db.add(student)
            created += 1

        db.flush()  # assign IDs without fully committing yet, so audit log record_id is stable

        write_audit_log(
            db,
            user_id=admin.id,
            action="roster_imported",
            table_name="students",
            record_id=0,  # batch action, not a single record
            new_value={
                "filename": filename,
                "created": created,
                "skipped_duplicates": len(skipped_duplicates),
                "row_errors": len(row_errors),
            },
        )
        db.commit()

        return RosterImportResult(created=created, skipped_duplicates=skipped_duplicates, row_errors=row_errors)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Server Crash: {trace}")

@router.get("/roster/sample")
def download_sample_csv():
    import io
    from fastapi.responses import StreamingResponse
    
    content = "sap_id,name,branch,year,gender,email\n500123456,Rahul Sharma,CSE,2,M,rahul@example.com\n500123457,Priya Patel,ECE,3,,priya@example.com\n"
    
    output = io.StringIO(content)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_roster.csv"}
    )


@router.get("", response_model=list[StudentSummary])
def list_roster(
    branch: Optional[str] = None,
    search: Optional[str] = Query(None, description="Matches name or SAP ID (partial)"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
):
    q = db.query(Student)
    if branch:
        q = q.filter(Student.branch == branch)
    if search:
        like = f"%{search}%"
        q = q.filter((Student.name.ilike(like)) | (Student.sap_id.ilike(like)))
    return q.order_by(Student.branch, Student.name).limit(limit).all()


@router.get("/stats-by-branch")
def roster_stats_by_branch(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
):
    from sqlalchemy import func
    rows = (
        db.query(Student.branch, func.count(Student.id))
        .group_by(Student.branch)
        .order_by(Student.branch)
        .all()
    )
    return [{"branch": b, "total_students": c} for b, c in rows]
