"""knowledge 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_knowledge_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/knowledge-bases")
    async def list_knowledge_bases(
        request: Request,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        return await self.knowledge_service.list_bases(
            tenant_id=(
                principal.tenant_id
                if principal
                else "default"
            ),
            roles=(
                principal.roles
                if principal
                else frozenset({"platform_admin"})
            ),
        )

    @self.fastapi.post("/v1/knowledge-bases")
    async def create_knowledge_base(
        payload: KnowledgeBaseCreateRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.knowledge_service.create_base(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                name=payload.name,
                description=payload.description,
                visibility=payload.visibility,
                allowed_roles=payload.allowed_roles,
                actor_id=self._actor_id(principal),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/knowledge-bases/{knowledge_base_id}/documents/upload"
    )
    async def upload_knowledge_document(
        knowledge_base_id: str,
        request: Request,
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_ingestion_service is None:
            raise HTTPException(
                status_code=503,
                detail="Knowledge ingestion is not configured.",
            )
        content = await file.read(
            self.knowledge_upload_max_bytes + 1
        )
        if len(content) > self.knowledge_upload_max_bytes:
            raise HTTPException(
                status_code=413,
                detail="Knowledge document is too large.",
            )
        try:
            return await self.knowledge_ingestion_service.submit(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                knowledge_base_id=knowledge_base_id,
                filename=file.filename or "document",
                content_type=(
                    file.content_type
                    or "application/octet-stream"
                ),
                content=content,
                actor_id=self._actor_id(principal),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail=str(error)
            ) from error

    @self.fastapi.get(
        "/v1/knowledge-bases/{knowledge_base_id}/documents"
    )
    async def list_knowledge_documents(
        knowledge_base_id: str,
        request: Request,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.knowledge_service.list_documents(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                knowledge_base_id=knowledge_base_id,
                limit=limit,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/knowledge-bases/{knowledge_base_id}/documents/upload-intent"
    )
    async def create_knowledge_upload_intent(
        knowledge_base_id: str,
        payload: KnowledgeUploadIntentRequest,
        request: Request,
    ) -> dict[str, Any]:
        """签发MinIO预签名URL，使大文件不经过API进程。"""
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_ingestion_service is None:
            raise HTTPException(
                status_code=503,
                detail="Knowledge ingestion is not configured.",
            )
        if payload.size_bytes > self.knowledge_upload_max_bytes:
            raise HTTPException(
                status_code=413,
                detail="Knowledge document is too large.",
            )
        try:
            return await (
                self.knowledge_ingestion_service
                .create_upload_intent(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    knowledge_base_id=knowledge_base_id,
                    filename=payload.filename,
                    content_type=payload.content_type,
                    actor_id=self._actor_id(principal),
                    expires_seconds=(
                        self
                        .knowledge_presigned_upload_expiry_seconds
                    ),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/knowledge-bases/{knowledge_base_id}/documents/"
        "{document_id}/commit-upload"
    )
    async def commit_knowledge_upload(
        knowledge_base_id: str,
        document_id: str,
        request: Request,
    ) -> dict[str, Any]:
        """确认直传对象存在，并提交给持久化解析Worker。"""
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_ingestion_service is None:
            raise HTTPException(status_code=503)
        try:
            document = await (
                self.knowledge_ingestion_service.commit_upload(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    knowledge_base_id=knowledge_base_id,
                    document_id=document_id,
                    maximum_bytes=self.knowledge_upload_max_bytes,
                )
            )
            return document
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/knowledge-bases/{knowledge_base_id}/documents/upload-batch"
    )
    async def upload_knowledge_documents_batch(
        knowledge_base_id: str,
        request: Request,
        files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_ingestion_service is None:
            raise HTTPException(
                status_code=503,
                detail="Knowledge ingestion is not configured.",
            )
        if len(files) > self.knowledge_upload_batch_max_files:
            raise HTTPException(
                status_code=413,
                detail=(
                    "单批文件数量不能超过 "
                    f"{self.knowledge_upload_batch_max_files} 个。"
                ),
            )
        async def iter_uploads():
            """逐个读取和释放上传文件，避免批次内容同时驻留内存。"""
            for file in files:
                filename = file.filename or "document"
                try:
                    content = await file.read(
                        self.knowledge_upload_max_bytes + 1
                    )
                    if len(content) > self.knowledge_upload_max_bytes:
                        yield {
                            "filename": filename,
                            "upload_error": (
                                f"文件 {filename} 超过单文件大小限制。"
                            ),
                        }
                        continue
                    yield {
                        "filename": filename,
                        "content_type": (
                            file.content_type
                            or "application/octet-stream"
                        ),
                        "content": content,
                    }
                finally:
                    # Starlette UploadFile可能持有磁盘临时文件，处理后立即关闭。
                    await file.close()
        try:
            return (
                await self.knowledge_ingestion_service.ingest_batch(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    knowledge_base_id=knowledge_base_id,
                    files=iter_uploads(),
                    actor_id=self._actor_id(principal),
                    total_count=len(files),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail=str(error)
            ) from error

    @self.fastapi.get(
        "/v1/knowledge-bases/{knowledge_base_id}/ingestion-batches"
    )
    async def list_knowledge_ingestion_batches(
        knowledge_base_id: str,
        request: Request,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        return await self.knowledge_service.list_ingestion_batches(
            tenant_id=(
                principal.tenant_id if principal else "default"
            ),
            knowledge_base_id=knowledge_base_id,
            limit=limit,
        )

    @self.fastapi.post(
        "/v1/knowledge-bases/{knowledge_base_id}/documents"
    )
    async def register_knowledge_document(
        knowledge_base_id: str,
        payload: KnowledgeDocumentRegisterRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        try:
            return await (
                self.knowledge_service.register_document(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    knowledge_base_id=knowledge_base_id,
                    title=payload.title,
                    object_key=payload.object_key,
                    mime_type=payload.mime_type,
                    content_hash=payload.content_hash,
                    size_bytes=payload.size_bytes,
                    metadata=payload.metadata,
                    actor_id=self._actor_id(principal),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404, detail=str(error)
            ) from error

    @self.fastapi.put(
        "/v1/knowledge-documents/{document_id}/chunks"
    )
    async def replace_knowledge_chunks(
        document_id: str,
        payload: KnowledgeChunksReplaceRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.knowledge_service.replace_chunks(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                document_id=document_id,
                chunks=[
                    item.model_dump()
                    for item in payload.chunks
                ],
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/knowledge-bases/{knowledge_base_id}/search"
    )
    async def search_knowledge_base(
        knowledge_base_id: str,
        payload: KnowledgeSearchRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.knowledge_service.search(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                roles=(
                    principal.roles
                    if principal
                    else frozenset({"platform_admin"})
                ),
                knowledge_base_id=knowledge_base_id,
                query=payload.query,
                limit=payload.limit,
            )
        except PermissionError as error:
            raise HTTPException(
                status_code=403, detail=str(error)
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=404, detail=str(error)
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=503, detail=str(error)
            ) from error

    @self.fastapi.get(
        "/v1/knowledge-documents/{document_id}"
    )
    async def get_knowledge_document(
        document_id: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.knowledge_service.get_document(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                document_id=document_id,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/knowledge-documents/{document_id}/reindex",
        status_code=202,
    )
    async def reindex_knowledge_document(
        document_id: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.knowledge_service.reindex_document(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                document_id=document_id,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404, detail=str(error)
            ) from error

    @self.fastapi.delete(
        "/v1/knowledge-documents/{document_id}",
        status_code=202,
    )
    async def delete_knowledge_document(
        document_id: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        tenant_id = (
            principal.tenant_id
            if principal
            else "default"
        )
        try:
            if self.knowledge_ingestion_service is not None:
                return await (
                    self.knowledge_ingestion_service.delete_document(
                        tenant_id=tenant_id,
                        document_id=document_id,
                    )
                )
            result = (
                await self.knowledge_service.begin_document_delete(
                    tenant_id=tenant_id,
                    document_id=document_id,
                )
            )
            if result["ready_to_finalize"]:
                document = await self.knowledge_service.get_document(
                    tenant_id=tenant_id,
                    document_id=document_id,
                )
                if document["object_key"]:
                    raise RuntimeError(
                        "MinIO is required to delete this document."
                    )
                await (
                    self.knowledge_service.finalize_document_delete(
                        document_id=document_id
                    )
                )
                result["status"] = "deleted"
            return result
        except ValueError as error:
            raise HTTPException(
                status_code=404, detail=str(error)
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=503, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/knowledge-documents/{document_id}/retry-parsing"
    )
    async def retry_knowledge_document_parsing(
        document_id: str,
        request: Request,
    ) -> dict[str, Any]:
        """人工恢复达到重试上限或质量门禁失败的解析任务。"""
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        if self.knowledge_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.knowledge_service.requeue_failed_parsing(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                document_id=document_id,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error

    @self.fastapi.get("/v1/vector-outbox/dead-letters")
    async def list_vector_dead_letters(
        request: Request,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        outbox = self.container.get(VectorOutboxService)
        return await outbox.list_dead_letters(
            tenant_id=(
                principal.tenant_id
                if principal
                else "default"
            ),
            limit=min(max(limit, 1), 500),
        )

    @self.fastapi.post(
        "/v1/vector-outbox/dead-letters/{event_id}/retry"
    )
    async def retry_vector_dead_letter(
        event_id: str,
        request: Request,
    ) -> dict[str, str]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "knowledge_admin"
        )
        try:
            await self.container.get(
                VectorOutboxService
            ).retry_dead_letter(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                event_id=event_id,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404, detail=str(error)
            ) from error
        return {"status": "pending", "event_id": event_id}

    @self.fastapi.post(
        "/v1/memory/{agent_name}/search"
    )
    async def search_user_memory(
        agent_name: str,
        payload: MemoryQueryRequest,
        request: Request,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._authorize_agent(principal, agent_name)
        tenant_id = (
            principal.tenant_id
            if principal
            else payload.tenant_id
        )
        user_id = (
            principal.user_id
            if principal
            else payload.user_id
        )
        namespace = self.memory_manager.build_namespace(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_name,
        )
        return [
            asdict(item)
            for item in await self.memory_manager.recall(
                payload.query,
                payload.limit,
                namespace,
            )
        ]
