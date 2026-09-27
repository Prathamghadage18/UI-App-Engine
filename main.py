from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers import pages, api

app = FastAPI(title="PrintOps SCADA Dashboard")

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(pages.router)
app.include_router(api.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="localhost", port=8000, reload=True)