# Copyright (c) 2024 Microsoft Corporation. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project.
#

import asyncio
from typing import Any

from sentence_transformers import SentenceTransformer

from toolkit.AI.base_embedder import BaseEmbedder
from toolkit.AI.defaults import DEFAULT_LLM_MAX_TOKENS, DEFAULT_LOCAL_EMBEDDING_MODEL
from toolkit.helpers.constants import CACHE_PATH


class LocalEmbedder(BaseEmbedder):
    def __init__(
        self,
        db_name: str = "embeddings",
        db_path=CACHE_PATH,
        max_tokens=DEFAULT_LLM_MAX_TOKENS,
    ):
        super().__init__(db_name, db_path, max_tokens)
        self.local_client = SentenceTransformer(DEFAULT_LOCAL_EMBEDDING_MODEL)

    def _generate_embedding(self, text: str | list[str]) -> list | Any:
        return self.local_client.encode(text).tolist()

    async def _generate_embedding_async(self, text: str) -> list | Any:
        await asyncio.sleep(0)

        return self._generate_embedding(text)