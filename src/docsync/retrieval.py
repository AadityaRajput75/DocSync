import uuid

import httpx
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from docsync.repository import chunks, digest, tokens


class OllamaEmbeddings:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.version = None

    async def fingerprint(self):
        if self.version is None:
            async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
                response = await client.get(self.settings.ollama_url + "/api/tags")
                response.raise_for_status()
                model = next((m for m in response.json()["models"]
                              if m["name"] == self.settings.embed_model), None)
                if not model:
                    raise ValueError(f"Install embedding model with: ollama pull {self.settings.embed_model}")
                if model.get("remote_host") or model.get("remote_model") or "cloud" in self.settings.embed_model.lower():
                    raise ValueError("Embeddings must use a downloaded local model")
                self.version = model["digest"]
        return self.version

    async def embed(self, text, query=False):
        version = await self.fingerprint()
        prefixed = ("search_query: " if query else "search_document: ") + text
        key = digest(version + prefixed)
        cached = self.store.vector(key)
        if cached is not None:
            return cached
        async with httpx.AsyncClient(trust_env=False, timeout=180) as client:
            response = await client.post(self.settings.ollama_url + "/api/embed", json={
                "model": self.settings.embed_model, "input": prefixed, "truncate": False,
                "keep_alive": "0s"})
            response.raise_for_status()
        vector = response.json()["embeddings"][0]
        return self.store.vector(key, vector)


class Retriever:
    def __init__(self, settings, store, embeddings=None, client=None):
        self.settings, self.store = settings, store
        self.embeddings = embeddings or OllamaEmbeddings(settings, store)
        self._client = client

    @property
    def client(self):
        # Open embedded storage only after the worker has acquired its queue lock.
        if self._client is None:
            self._client = (QdrantClient(path=str(self.settings.data_dir / "vectors"))
                            if self.settings.qdrant_mode == "embedded" else
                            QdrantClient(url=self.settings.qdrant_url, timeout=20, check_compatibility=False))
        return self._client

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    async def collection(self):
        return "docsync_" + digest(await self.embeddings.fingerprint())[:16]

    async def index(self, snapshot):
        if isinstance(self.embeddings, OllamaEmbeddings):
            self.embeddings.version = None  # detect a model replacement between indexing runs
        items, symbols = chunks(snapshot)
        collection = await self.collection()
        points = []
        for item in items:
            # Bound metadata as well as source text to stay below the model input limit.
            vector = await self.embeddings.embed(item["path"][:120] + "\n" + item["symbol"][:120] + "\n" + item["text"])
            if not self.client.collection_exists(collection):
                self.client.create_collection(collection, vectors_config=models.VectorParams(
                    size=len(vector), distance=models.Distance.COSINE))
            points.append(models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, snapshot["id"] + item["id"])),
                                             vector=vector, payload={**item, "snapshot_id": snapshot["id"]}))
            if len(points) == 64:
                self.client.upsert(collection, points, wait=True)
                points = []
        if points:
            self.client.upsert(collection, points, wait=True)
        self.store.put("index", {"id": snapshot["id"], "chunks": items, "symbols": symbols,
                                 "collection": collection})
        return len(items)

    async def search(self, snapshot, query, mode="hybrid"):
        if mode == "none":
            return []
        index = self.store.get("index", snapshot["id"])
        items = index["chunks"]
        if not items:
            return []
        terms = tokens(query)
        corpus = [tokens(c["path"] + " " + c["symbol"] + " " + c["text"]) for c in items]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(terms)
        lexical = [items[i]["id"] for i in sorted(range(len(items)), key=lambda i: scores[i], reverse=True)
                   if set(terms).intersection(corpus[i])][:24]
        direct = [c["id"] for c in items if c["symbol"] not in {"", "<module>"}
                  and c["symbol"].split(".")[-1] in query][:16]
        related_names = {call.split(".")[-1] for s in index["symbols"]
                         if s["name"].split(".")[-1] in query for call in s["calls"]}
        related = [c["id"] for c in items if c["symbol"].split(".")[-1] in related_names][:16]
        rankings = [lexical, direct, related]
        if mode == "hybrid":
            vector = await self.embeddings.embed(query[:1200], query=True)
            hits = self.client.query_points(index["collection"], query=vector, limit=24,
                                           query_filter=models.Filter(must=[models.FieldCondition(
                                               key="snapshot_id", match=models.MatchValue(value=snapshot["id"]))]))
            rankings.append([h.payload["id"] for h in hits.points])
        fused = {}
        for ranking in rankings:
            for rank, item_id in enumerate(ranking):
                fused[item_id] = fused.get(item_id, 0) + 1 / (60 + rank + 1)
        mapping = {c["id"]: c for c in items}
        return [mapping[key] for key in sorted(fused, key=fused.get, reverse=True)[:8]]
