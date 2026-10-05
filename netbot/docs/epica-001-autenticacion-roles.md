# Épica 001: autenticación y roles

La API implementa autenticación con contraseñas Argon2, tokens JWT de acceso de
corta duración y tokens de actualización opacos, almacenados únicamente como
hash. La rotación revoca el refresh token usado; `logout` también lo revoca.

## Endpoints

- `POST /auth/login` con `{email, password}` devuelve `access_token` y
  `refresh_token`.
- `POST /auth/refresh`, `POST /auth/logout` y `GET /auth/me`.
- `GET/POST/PATCH /admin/users` y `GET/POST /admin/roles` requieren un usuario
  con rol `admin`.

Los roles iniciales son `admin`, `operador` y `visor`. Se crean al iniciar la
aplicación. Para crear el primer administrador se pueden definir
`ADMIN_EMAIL` y `ADMIN_PASSWORD` en el entorno (solo se usa si ese email aún no
existe). En producción se debe cambiar `JWT_SECRET_KEY` y usar HTTPS.

La persistencia se configura con `DATABASE_URL`; ejecutar `alembic upgrade head`
aplica la migración versionada. El arranque también crea tablas para facilitar
el desarrollo local; las migraciones siguen siendo el mecanismo recomendado
para despliegues.
