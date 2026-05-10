"""
Middleware de security headers (CSP, HSTS, X-Frame, etc).
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)

        # HSTS - forca HTTPS por 1 ano (apenas em prod)
        import os
        if os.getenv("ENV", "").lower() == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Anti clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Bloqueia MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Sem referrer cross-origin
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CSP basico - API so retorna JSON/HTML pequeno
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'"
        )
        # Permissions Policy minima
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
        )

        return response
