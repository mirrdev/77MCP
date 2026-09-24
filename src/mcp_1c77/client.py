"""Python SDK клиент для MCP-сервера 1C:Предприятие 7.7.

Удобный программный доступ к метаданным конфигурации через HTTP API.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, quote


class ConfigError(Exception):
    """Ошибка конфигурации или подключения."""
    pass


class ObjectNotFoundError(Exception):
    """Объект не найден в конфигурации."""
    pass


class MetadataClient:
    """Клиент для работы с метаданными 1С 7.7 через REST API."""
    
    def __init__(self, base_url: str = "http://localhost:8099"):
        """Инициализация клиента.
        
        Args:
            base_url: Базовый URL сервера (по умолчанию http://localhost:8099)
        """
        self.base_url = base_url.rstrip('/')
    
    def _request(self, endpoint: str, method: str = "GET", 
                 params: Optional[dict] = None, 
                 data: Optional[dict] = None) -> dict:
        """Выполнить HTTP запрос к API.
        
        Args:
            endpoint: Endpoint относительно base_url
            method: HTTP метод (GET, POST)
            params: Query параметры
            data: JSON данные для POST запроса
            
        Returns:
            dict: Ответ API
            
        Raises:
            ConfigError: Ошибка подключения или сервера
        """
        url = f"{self.base_url}{endpoint}"
        
        if params:
            url += "?" + urlencode(params)
        
        headers = {"Content-Type": "application/json"}
        
        body = None
        if data and method == "POST":
            body = json.dumps(data).encode('utf-8')
        
        req = Request(url, data=body, headers=headers, method=method)
        
        try:
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                if not result.get('ok', True):
                    raise ConfigError(result.get('error', 'Unknown error'))
                return result
        except HTTPError as e:
            raise ConfigError(f"HTTP Error {e.code}: {e.reason}")
        except URLError as e:
            raise ConfigError(f"Connection error: {e.reason}")
    
    # === Информация о сервере ===
    
    def get_server_info(self) -> dict:
        """Получить информацию о сервере API."""
        return self._request("/api")
    
    def get_status(self) -> dict:
        """Получить статус загруженной конфигурации."""
        return self._request("/api/status")
    
    def is_loaded(self) -> bool:
        """Проверить, загружена ли конфигурация."""
        status = self.get_status()
        return status.get('loaded', False)
    
    def get_config_info(self) -> Optional[dict]:
        """Получить информацию о конфигурации."""
        status = self.get_status()
        if status.get('loaded'):
            return {
                'name': status.get('name'),
                'version': status.get('version'),
                'counts': status.get('counts', {})
            }
        return None
    
    # === Список объектов ===
    
    def list_objects(self, object_type: str = "") -> dict:
        """Получить список объектов метаданных.
        
        Args:
            object_type: Тип объекта для фильтрации (Справочник, Документ, и т.д.)
            
        Returns:
            dict: Словарь {type: [names]}
        """
        params = {'type': object_type} if object_type else {}
        return self._request("/api/objects", params=params)
    
    def search(self, query: str) -> list:
        """Поиск по метаданным.
        
        Args:
            query: Строка поиска
            
        Returns:
            list: Список найденных объектов
        """
        result = self._request("/api/search", params={'q': query})
        return result.get('results', [])
    
    # === Детали объекта ===
    
    def get_object(self, object_type: str, name: str) -> str:
        """Получить детальную информацию об объекте.
        
        Args:
            object_type: Тип объекта
            name: Имя объекта
            
        Returns:
            str: Текстовое описание объекта
        """
        result = self._request(f"/api/objects/{quote(object_type)}/{quote(name)}")
        return result.get('data', '')
    
    def get_module(self, object_type: str, name: str) -> Optional[str]:
        """Получить исходный код модуля объекта.
        
        Args:
            object_type: Тип объекта
            name: Имя объекта
            
        Returns:
            str: Код модуля или None если отсутствует
        """
        result = self._request(f"/api/objects/{quote(object_type)}/{quote(name)}/module")
        return result.get('module')
    
    def get_form(self, object_type: str, name: str) -> Optional[str]:
        """Получить описание формы объекта.
        
        Args:
            object_type: Тип объекта
            name: Имя объекта
            
        Returns:
            str: Описание формы или None если отсутствует
        """
        result = self._request(f"/api/objects/{quote(object_type)}/{quote(name)}/form")
        return result.get('form')
    
    # === Зависимости ===
    
    def get_dependencies(self, object_type: str, name: str) -> list:
        """Получить зависимости объекта (что он использует).
        
        Args:
            object_type: Тип объекта
            name: Имя объекта
            
        Returns:
            list: Список зависимостей
        """
        result = self._request(f"/api/objects/{quote(object_type)}/{quote(name)}/dependencies")
        return result.get('dependencies', [])
    
    def get_dependents(self, object_type: str, name: str) -> list:
        """Получить зависимые объекты (кто использует этот объект).
        
        Args:
            object_type: Тип объекта
            name: Имя объекта
            
        Returns:
            list: Список зависимых объектов
        """
        result = self._request(f"/api/objects/{quote(object_type)}/{quote(name)}/dependents")
        return result.get('dependents', [])
    
    # === Валидация ===
    
    def validate_field_path(self, object_type: str, name: str, path: str) -> dict:
        """Проверить валидность пути к реквизиту.
        
        Args:
            object_type: Тип объекта
            name: Имя объекта
            path: Путь к реквизиту
            
        Returns:
            dict: {'valid': bool, 'message': str}
        """
        return self._request("/api/validate/path", params={
            'type': object_type,
            'name': name,
            'path': path
        })
    
    def validate_query(self, query_text: str) -> dict:
        """Проверить запрос 1С на корректность путей.
        
        Args:
            query_text: Текст запроса
            
        Returns:
            dict: {'valid': bool, 'message': str}
        """
        return self._request("/api/validate/query", method="POST", 
                            data={'query': query_text})
    
    # === Экспорт ===
    
    def export_config(self, save_to_file: bool = False, path: str = "") -> Any:
        """Экспорт всей конфигурации в JSON.
        
        Args:
            save_to_file: Сохранить в файл
            path: Путь для сохранения
            
        Returns:
            dict или str: JSON данные или сообщение о сохранении
        """
        data = self._request("/api/export").get("data", {})
        if save_to_file:
            if not path:
                raise ConfigError("Укажите путь локального JSON-файла.")
            from pathlib import Path
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        return data
    
    def export_object(self, object_type: str, name: str) -> dict:
        """Экспорт объекта в JSON.
        
        Args:
            object_type: Тип объекта
            name: Имя объекта
            
        Returns:
            dict: JSON представление объекта
        """
        result = self._request(f"/api/export/{quote(object_type)}/{quote(name)}")
        return result.get('data', {})
    
    def reload_config(self, path: str = "") -> dict:
        """Перезагрузить конфигурацию.
        
        Args:
            path: Путь к файлу (опционально)
            
        Returns:
            dict: Результат перезагрузки
        """
        return self._request("/api/reload", method="POST", data={'path': path})


# === Удобные функции для быстрого доступа ===

_default_client: Optional[MetadataClient] = None


def init_client(base_url: str = "http://localhost:8099") -> MetadataClient:
    """Инициализировать глобальный клиент.
    
    Args:
        base_url: Базовый URL сервера
        
    Returns:
        MetadataClient: Созданный клиент
    """
    global _default_client
    _default_client = MetadataClient(base_url)
    return _default_client


def get_client() -> MetadataClient:
    """Получить глобальный клиент.
    
    Returns:
        MetadataClient: Клиент
        
    Raises:
        ConfigError: Если клиент не инициализирован
    """
    if _default_client is None:
        raise ConfigError("Client not initialized. Call init_client() first.")
    return _default_client


# === Примеры использования ===

if __name__ == "__main__":
    # Пример использования
    print("=== 1C 7.7 Metadata Client Example ===\n")
    
    client = MetadataClient()
    
    try:
        # Проверка статуса
        print("Server status:")
        status = client.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
        
        # Поиск
        print("\n\nSearch for 'Склад':")
        results = client.search("Склад")
        for item in results[:5]:
            print(f"  - {item}")
        
        # Список справочников
        print("\n\nCatalogs:")
        catalogs = client.list_objects("Справочник")
        print(json.dumps(catalogs, indent=2, ensure_ascii=False)[:500] + "...")
        
    except ConfigError as e:
        print(f"Error: {e}")
        print("\nMake sure the server is running at http://localhost:8099")
