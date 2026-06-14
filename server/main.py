"""aimem-reference FastAPI app.

Reference implementation of draft-vu-aimem-bundle-00.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .db import init_db, close_db
from .routes import brain, admin, meta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("aimem")

app = FastAPI(
    title="AIMEM Bundle Reference",
    version="0.1.0",
    description=(
        "Reference Producer/Consumer for the AIMEM Bundle Format "
        "(draft-vu-aimem-bundle-00). Apache-2.0."
    ),
)


@app.on_event("startup")
async def _startup():
    await init_db()
    logger.info("aimem-reference started")


@app.on_event("shutdown")
async def _shutdown():
    await close_db()


app.include_router(meta.router)
app.include_router(brain.router)
app.include_router(admin.router)
