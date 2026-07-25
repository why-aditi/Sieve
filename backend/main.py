from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Sieve API")

# ponytail: wildcard CORS. There is no auth and no cookie, so this grants nothing.
# Pin to the Vercel origin the moment a session cookie exists.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "sieve"}
