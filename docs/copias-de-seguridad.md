# Copias de seguridad de la base de datos

Todos los días a las 04:17 (hora de Argentina) GitHub Actions saca una copia de la base de Trappi, la **cifra**, prueba que se puede restaurar y la guarda en el repositorio como *artifact*:

- las diarias quedan **35 días**;
- la del domingo queda **90 días** (lo máximo que permite GitHub).

Es gratis. El archivo de la tarea es [`.github/workflows/backup-db.yml`](../.github/workflows/backup-db.yml).

> El repositorio es público: cualquiera con cuenta de GitHub puede descargar los artifacts. Por eso la copia **siempre** sale cifrada con AES-256: sin la clave no se puede abrir. Si falta la clave, la tarea falla y no sube nada.

## Configurarlo (una sola vez)

1. **La dirección de la base.** En Render, entrá a la base de datos → **Connections** → copiá la **External Database URL** (empieza con `postgresql://`).
2. **Una clave larga.** Inventá una frase de por lo menos 20 caracteres (mejor 30 o más; por ejemplo cuatro o cinco palabras al azar con números). **Guardala también fuera de GitHub**, en tu gestor de contraseñas o anotada en un lugar seguro: sin esa clave las copias no sirven.
3. En GitHub: **Settings → Secrets and variables → Actions → New repository secret** y cargá:
   - `BACKUP_DATABASE_URL`: la dirección del paso 1.
   - `BACKUP_PASSPHRASE`: la clave del paso 2.
4. Probalo: **Actions → Copia de seguridad de la base → Run workflow**. En unos minutos tiene que terminar en verde con "Restauración probada: OK".

Los secretos no se ven en ningún lado: GitHub los tapa en los registros y la tarea no imprime ningún dato de la base.

## Restaurar una copia

Para volver atrás después de un problema, o para pasar los datos a una base nueva.

1. **Descargar.** En GitHub: **Actions → Copia de seguridad de la base**, elegí el día y descargá el artifact `trappi-db-AAAA-MM-DD` (es un `.zip` con el `.dump.gpg` y su `.sha256`).
2. **Comprobar y descifrar** (en una compu con `gpg` y las herramientas de PostgreSQL 17, por ejemplo Linux o WSL en Windows):

   ```bash
   unzip trappi-db-2026-10-28.zip
   sha256sum -c trappi-2026-10-28.sha256
   gpg --decrypt --output trappi.dump trappi-2026-10-28.dump.gpg   # pide la clave
   ```

3. **Cargar en una base vacía.** Lo más seguro es crear una base **nueva** en Render (o local) y restaurar ahí, sin pisar la actual:

   ```bash
   pg_restore --no-owner --no-acl --exit-on-error --dbname="postgresql://USUARIO:CLAVE@HOST/BASE" trappi.dump
   ```

4. **Apuntar Trappi a la base restaurada**: en Render, cambiá `DATABASE_URL` del servicio web por la dirección de la base nueva y reiniciá. Al arrancar, Trappi aplica las migraciones que falten.
5. **Borrá** `trappi.dump` de tu compu cuando termines: tiene todos los datos sin cifrar.

## Cosas a tener en cuenta

- **Render gratis:** según sus condiciones actuales, las bases de PostgreSQL del plan gratis vencen un tiempo después de creadas. Revisá la fecha en el panel de Render y, antes de que venza, restaurá la última copia en la base nueva.
- **GitHub pausa las tareas programadas** de un repositorio público después de 60 días sin cambios. Si eso pasa, te llega un mail; se vuelve a prender desde **Actions** con un clic.
- **La copia es de la base, no de las fotos.** Las fotos están en Cloudinary, que las guarda aparte.
- **Si la tarea falla**, GitHub te manda un mail. Las causas más comunes: la base de Render cambió de dirección (actualizá `BACKUP_DATABASE_URL`) o venció.
