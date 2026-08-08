"""路由实现共享的内部依赖。

该文件不是平台公开 Interface；它只避免十个路由模块重复维护同一组接入层导入。
"""



import asyncio
import csv
import io
import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.a2a import RemoteA2AAgent
from app.agent import AgentConfig, AgentContext, AgentPackageManager, AgentTestCase
from app.bootstrap.api_schemas import *  # noqa: F403 - internal route schema facade
from app.core.exceptions import PlatformError
from app.core.metrics import PlatformMetrics
from app.llm import EmbeddingRequest, RerankRequest
from app.prompt import PromptEvaluator, PromptTestCase, PromptTrafficVariant
from app.runtime import EventBus
from app.tool import PythonToolCandidateCatalog
from app.vector import VectorOutboxService
