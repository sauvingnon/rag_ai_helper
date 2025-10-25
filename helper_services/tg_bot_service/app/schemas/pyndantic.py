from pydantic import BaseModel
from typing import Type, List, Dict, Any

def to_pydantic_model(model: Type[BaseModel], data: Dict[str, Any]) -> BaseModel:
    """
    Преобразовать данные в модель Pydantic.

    :param model: модель, в которую нужно преобразовать
    :param data: данные (словарь или JSON)
    :return: объект модели
    """
    return model(**data)  # создаём объект модели с помощью распаковки данных

def to_pydantic_models(model: Type[BaseModel], data: List[Dict[str, Any]]) -> List[BaseModel]:
    """
    Преобразует массив данных в список объектов Pydantic модели.

    :param model: модель, в которую нужно преобразовать данные
    :param data: список словарей с данными
    :return: список объектов модели
    """
    return [model(**item) for item in data]
