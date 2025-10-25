import re

def prepare_query_for_search(query: str) -> str:
    """
    Подготавливает пользовательский запрос для dense retrieval и rerank.
    - Приводит к нижнему регистру
    - Убирает лишние пробелы, табуляции, переносы строк
    - Убирает символы, которые не несут смысла (например, пунктуацию, кроме букв и цифр)
    
    :param query: исходный текст запроса пользователя
    :return: очищенный и нормализованный текст для поиска
    """
    # Приводим к нижнему регистру
    query = query.lower()
    
    # Убираем лишние пробелы, табуляции и переносы строк
    query = re.sub(r'\s+', ' ', query).strip()
    
    # Оставляем только буквы, цифры и пробелы (можно расширить под рус/англ)
    query = re.sub(r'[^а-яa-z0-9\s]', '', query)
    
    return query


def clean_text(text: str) -> str:
    """Минимальная чистка текста: убираем лишние пробелы, переносы строк и html-теги"""
    text = re.sub(r"<.*?>", "", text)   # вырезаем html
    text = re.sub(r"\s+", " ", text)    # нормализуем пробелы
    return text.strip()

def chunk_text(text: str, max_len: int = 300) -> list[str]:
    """Делим текст на куски для векторизации"""
    words = text.split()
    chunks, chunk = [], []
    for word in words:
        if len(" ".join(chunk + [word])) > max_len:
            chunks.append(" ".join(chunk))
            chunk = [word]
        else:
            chunk.append(word)
    if chunk:
        chunks.append(" ".join(chunk))
    return chunks
