from fastapi import FastAPI

from rpim_shared import HealthStatus

app = FastAPI(title="RPIM Core API", docs_url=None, redoc_url=None)


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(service="core-api", leg="iran")
