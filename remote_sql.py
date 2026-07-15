"""Small DB-API-like adapter for the authenticated SQLConnect migration API."""
from __future__ import annotations
import re
from typing import Any
import requests

class RemoteSqlConnection:
    def __init__(self, base_url: str, token: str, timeout: int = 600):
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self.session = requests.Session()
        self.session.headers.update({"X-API-Token": token})
    def cursor(self): return RemoteSqlCursor(self)
    def commit(self): pass
    def rollback(self): pass
    def close(self): self.session.close()
    def request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            detail = ""
            if exc.response is not None:
                try: detail = exc.response.json().get("detail", "")
                except ValueError: detail = exc.response.text
            raise RuntimeError(f"SQLConnect bridge request failed: {detail or exc}") from exc

class RemoteSqlCursor:
    def __init__(self, connection):
        self.connection, self.description, self.rowcount, self.fast_executemany = connection, None, -1, False
        self._rows = []
    @staticmethod
    def _named_parameters(sql, parameters=None):
        if parameters is None: return sql, {}
        if isinstance(parameters, dict): return sql, parameters
        if not isinstance(parameters, (list, tuple)): parameters = (parameters,)
        values, names = iter(parameters), []
        def replace(_):
            name = f"p{len(names)}"; names.append(name); return f":{name}"
        converted, result = re.sub(r"\?", replace, sql), {}
        for name in names:
            try: result[name] = next(values)
            except StopIteration as exc: raise ValueError("Not enough SQL parameters supplied") from exc
        try: next(values); raise ValueError("Too many SQL parameters supplied")
        except StopIteration: return converted, result
    def execute(self, sql, parameters=None):
        sql, parameters = self._named_parameters(sql, parameters)
        if sql.lstrip().upper().startswith(("SELECT", "WITH")):
            result = self.connection.request("/migration/query", {"sql": sql, "parameters": parameters})
            keys = result.get("columns", [])
            self.description = [(key, None, None, None, None, None, None) for key in keys]
            self._rows, self.rowcount = [tuple(row.get(key) for key in keys) for row in result.get("rows", [])], len(result.get("rows", []))
        else:
            result = self.connection.request("/migration/execute", {"sql": sql, "parameters": parameters})
            self.description, self._rows, self.rowcount = None, [], result.get("rows_affected", -1)
        return self
    def executemany(self, sql, parameter_sets):
        converted_sql, converted_parameters = None, []
        for parameters in parameter_sets:
            candidate_sql, candidate_parameters = self._named_parameters(sql, parameters)
            if converted_sql is None: converted_sql = candidate_sql
            elif converted_sql != candidate_sql: raise ValueError("Inconsistent batch SQL")
            converted_parameters.append(candidate_parameters)
        if not converted_parameters: self.rowcount = 0; return self
        result = self.connection.request("/migration/execute-many", {"sql": converted_sql, "parameter_sets": converted_parameters})
        self.description, self._rows, self.rowcount = None, [], result.get("rows_affected", -1)
        return self
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None
    def close(self): pass
