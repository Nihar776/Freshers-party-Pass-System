import os
import base64
import re
from sqlalchemy.orm import Session
from database import SessionLocal
from schema_v2 import Student

EXPORT_DIR = "screenshots_export"

def export_screenshots():
    if not os.path.exists(EXPORT_DIR):
        os.makedirs(EXPORT_DIR)
        
    db: Session = SessionLocal()
    try:
        # Fetch all students that have a screenshot uploaded
        students_with_ss = db.query(Student).filter(Student.payment_screenshot.isnot(None)).all()
        
        count = 0
        for student in students_with_ss:
            b64_data = student.payment_screenshot
            
            # Clean up base64 string if it contains the data URI prefix (e.g., data:image/jpeg;base64,...)
            if "base64," in b64_data:
                b64_data = b64_data.split("base64,")[1]
            
            # Remove any whitespace or newlines
            b64_data = re.sub(r'\s+', '', b64_data)
            
            try:
                image_bytes = base64.b64decode(b64_data)
                
                # Determine filename
                # If they are a group payer, prefix the filename to make it obvious for the treasurer
                prefix = "[GROUP_PAYER]_" if student.is_group_payer else ""
                
                # Sanitize name for filesystem
                safe_name = "".join(c for c in student.name if c.isalnum() or c in " ._-").strip()
                safe_sap = "".join(c for c in student.sap_id if c.isalnum()).strip()
                
                filename = f"{prefix}{safe_name}_{safe_sap}.jpg"
                filepath = os.path.join(EXPORT_DIR, filename)
                
                with open(filepath, "wb") as f:
                    f.write(image_bytes)
                    
                print(f"Exported: {filename}")
                count += 1
            except Exception as e:
                print(f"Failed to decode or save image for {student.name} (SAP: {student.sap_id}): {e}")
                
        print(f"\nSuccessfully exported {count} screenshots to the '{EXPORT_DIR}' folder.")
    except Exception as e:
        print(f"Database error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("Connecting to Supabase and fetching screenshots...")
    export_screenshots()
