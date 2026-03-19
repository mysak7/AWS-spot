import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    uvicorn.run("web.app:app", host="0.0.0.0", port=8080, reload=True)
