import os
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_search():
    print("Testing /api/student/search?query=57601260009")
    response = client.get("/api/student/search?query=57601260009")
    print("Status:", response.status_code)
    try:
        print("Response:", response.json())
    except Exception as e:
        print("Error parsing json:", e)
        print("Text:", response.text)

if __name__ == "__main__":
    test_search()
