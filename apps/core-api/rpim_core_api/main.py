from fastapi import FastAPI

from rpim_core_api.routers import auth, brain, brand_profile, content, onboarding, publish
from rpim_core_api.routers.qa_governance import gov_router, qa_router
from rpim_shared import HealthStatus

app = FastAPI(title="RPIM Core API", docs_url=None, redoc_url=None)
app.include_router(auth.router)
app.include_router(brand_profile.router)
app.include_router(onboarding.router)
app.include_router(brain.router)
app.include_router(content.router)
app.include_router(qa_router)
app.include_router(gov_router)
app.include_router(publish.router)


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(service="core-api", leg="iran")
