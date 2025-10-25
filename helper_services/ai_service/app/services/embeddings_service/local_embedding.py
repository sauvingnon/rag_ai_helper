from chromadb import EmbeddingFunction

class LocalEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model: str):
        self.model = model

    def __call__(self, input: list[str]) -> list[list[float]]:
        # Chroma ждёт именно параметр input, а не texts
        return self.model.encode(input).tolist()

    def name(self) -> str:
        return "local-sbert"