"""Small domain error type that the API layer turns into HTTP responses."""


class ServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def not_found(what: str = "Resource") -> ServiceError:
    return ServiceError(404, f"{what} not found")
