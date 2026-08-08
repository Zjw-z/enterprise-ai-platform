"""Independent Embedding/Reranker HTTP service entrypoint."""

from __future__ import annotations

import os
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.bootstrap import Bootstrap
from app.llm import EmbeddingRequest, LLMManager, RerankRequest


class EmbeddingPayload(BaseModel):
    model: str = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    dimensions: int | None = Field(default=None, gt=0)


class RerankPayload(BaseModel):
    model: str = Field(min_length=1)
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1)
    top_n: int | None = Field(default=None, gt=0)


def create_app() -> FastAPI:
    """Build only the inference-facing API around configured model profiles."""
    platform = Bootstrap(
        {"vector_outbox_worker_enabled": False}
    ).build()
    manager = platform.container.get(LLMManager)
    api_key = os.getenv("EAP_INFERENCE_API_KEY")
    app = FastAPI(
        title="Enterprise AI Inference Service",
        version="1.0.0",
    )

    async def authorize(
        authorization: str | None = Header(default=None),
    ) -> None:
        if api_key and authorization != f"Bearer {api_key}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready() -> dict[str, Any]:
        return {
            "status": "ready",
            "embedding_models": list(manager.embedding_models),
            "rerank_models": list(manager.rerank_models),
        }

    @app.post(
        "/v1/embeddings",
        dependencies=[Depends(authorize)],
    )
    async def embeddings(payload: EmbeddingPayload) -> dict[str, Any]:
        result = await manager.get_embedding(payload.model).embed(
            EmbeddingRequest(
                inputs=payload.inputs,
                dimensions=payload.dimensions,
            )
        )
        return {
            "model": result.model,
            "embeddings": result.embeddings,
            "metadata": result.metadata,
        }

    @app.post(
        "/v1/rerank",
        dependencies=[Depends(authorize)],
    )
    async def rerank(payload: RerankPayload) -> dict[str, Any]:
        result = await manager.get_reranker(payload.model).rerank(
            RerankRequest(
                query=payload.query,
                documents=payload.documents,
                top_n=payload.top_n,
            )
        )
        return {
            "model": result.model,
            "results": [
                {
                    "index": item.index,
                    "score": item.score,
                    "document": item.document,
                }
                for item in result.results
            ],
            "metadata": result.metadata,
        }

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("EAP_INFERENCE_HOST", "0.0.0.0"),
        port=int(os.getenv("EAP_INFERENCE_PORT", "8100")),
    )
