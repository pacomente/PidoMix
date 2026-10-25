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
| F1 | Pedido por teléfono (delivery o retiro) | F9 | Ventas (reimprimir / anular) |
| F2 | Cobrar (Alt+1…4 medio, Alt+4 mixto, Ctrl+1…5 billetes) | F10 | Cerrar caja (arqueo por billetes) |
| F3 | Buscar | F11 | Dejar en espera / retomar tickets |
| F4 | Pagar con Puntos Trappi | F12 | Configuración (impresoras, comanda de cocina, salir) |
| F5 | Aclaración del producto ("sin cebolla") | 1–9 | Los más vendidos |
| F6 | Monto libre | Ctrl+E | Retiro o ingreso de efectivo |
| F7 | Descuento (más del 10 %: PIN del dueño) | + / − / Supr | Cantidad / quitar |
| F8 | Reimprimir el último ticket (desde la 2.ª vez: PIN del dueño) | Ctrl+K | Cliente frecuente (por teléfono) |
| Ctrl+S | Salón (mesas) / volver al mostrador | Ctrl+R | Resumen del día y corte parcial (dueño) |
| Ctrl+M | Mesa: mandar lo nuevo a la cocina | Ctrl+P | Mesa: pre-cuenta |
| Ctrl+D | Mesa: dividir la cuenta | Clic derecho en un producto | Agotar / hay de nuevo |

## Desarrollo

```
flutter pub get
flutter run -d windows --dart-define=TRAPPI_API=http://localhost:8000 --dart-define=KIOSK=false
```

`KIOSK=false` abre la ventana normal en vez de pantalla completa. En Linux también compila (`flutter build linux`) para probar.
