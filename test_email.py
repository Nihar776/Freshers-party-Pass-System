import concurrent.futures
from database import SessionLocal
from schema_v2 import Student, PaymentStatus
from auth import generate_pass_token, generate_qr_image
from mailer import send_pass_email

db = SessionLocal()
student = db.query(Student).filter(Student.payment_status == PaymentStatus.VERIFIED).first()

if student:
    print(f"Testing background email for SAP ID: {student.sap_id}")
    token = generate_pass_token(sap_id=student.sap_id, pass_uuid=student.pass_uuid)
    qr_image = generate_qr_image(token)

    # Simulate FastAPI BackgroundTasks thread
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(
            send_pass_email,
            recipient_email=student.email,
            student_name=student.name,
            qr_image_bytes=qr_image,
            sap_id=student.sap_id,
        )
        try:
            future.result()
            print("Email sent successfully in background thread!")
        except Exception as e:
            print(f"Background thread failed: {e}")
else:
    print("No verified students found to test with.")
