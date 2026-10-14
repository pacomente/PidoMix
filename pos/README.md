# Trappi Caja (Windows)

Punto de venta para los comercios de Trappi. Corre a pantalla completa en una compu con Windows,
funciona sin internet y por cada venta genera un QR de **Puntos Trappi** que el cliente escanea para sumarlos a su cuenta.

- **Descarga:** el panel del local (Caja → Descargar) baja `trappi-caja-setup.exe` del release `caja-windows`,
  que arma `.github/workflows/caja-windows.yml` en cada cambio de `pos/` en `main`.
- **Vincular:** la primera vez se entra con el usuario del local. La contraseña no se guarda: Trappi le da a la caja
  un token propio que se anula desde el panel ("Desvincular todas las cajas").
- **Cajeros:** se crean en el panel con un PIN de 4 a 6 dígitos. Cerrar la caja, anular ventas, desvincular
  y salir del programa piden el PIN de un dueño.
- **Sin internet:** las ventas se guardan en la compu (`%APPDATA%\Trappi\Trappi Caja\trappi_caja`) y se suben solas
  cada 20 segundos. El servidor recalcula los precios del menú y no duplica ventas (cada una lleva su `client_uuid`).
- **Impresora:** térmica de 58 u 80 mm instalada en Windows; se elige con F12 e imprime directo, sin diálogo.
- **Pagar con Puntos Trappi (F4):** con el ticket armado, la caja muestra un código de 4 números. El cliente escanea el
  QR del mostrador (se imprime desde el panel → Caja), pone el código y confirma en su celular; la caja ve la confirmación
  sola y resta el descuento. Mientras tanto el ticket no se puede cambiar; cancelarlo devuelve los puntos. Necesita internet.
- **Lector de código de barras:** cualquiera USB que funcione como teclado. El código se carga en el producto desde el panel.

## Teclas

| Tecla | Acción | Tecla | Acción |
|---|---|---|---|
| F2 | Cobrar | F9 | Ventas (reimprimir / anular) |
| F3 | Buscar | F10 | Cerrar caja |
| F4 | Pagar con Puntos Trappi | | |
| F6 | Monto libre | F12 | Configuración (impresora, salir) |
| F7 | Descuento | 1–9 | Productos rápidos |
| F8 | Reimprimir el último ticket | + / − / Supr | Cantidad / quitar |

## Desarrollo

```
flutter pub get
flutter run -d windows --dart-define=TRAPPI_API=http://localhost:8000 --dart-define=KIOSK=false
```

`KIOSK=false` abre la ventana normal en vez de pantalla completa. En Linux también compila (`flutter build linux`) para probar.
