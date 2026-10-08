import { useLastNotificationResponse } from 'expo-notifications';
import { router } from 'expo-router';
import { useEffect, useRef } from 'react';
import { Platform } from 'react-native';

import { orderIdFrom, storeSlugFrom } from '@/lib/push';
import { useApp } from '@/state/app-state';

/** Al tocar un aviso de Trappi (con la app abierta, en segundo plano o cerrada) abre ese pedido. */
function Opener() {
  const response = useLastNotificationResponse();
  const { ready, orders } = useApp();
  const handled = useRef<string | null>(null);

  useEffect(() => {
    if (!ready || !response) return;
    const key = response.notification.request.identifier + response.notification.date;
    if (handled.current === key) return;
    handled.current = key;
    const id = orderIdFrom(response.notification);
    if (id && orders.some(o => o.id === id)) router.push({ pathname: '/order/[id]', params: { id: String(id) } });
    else if (!id) {
      const slug = storeSlugFrom(response.notification);
      if (slug) router.push({ pathname: '/store/[slug]', params: { slug } });
    }
  }, [ready, response, orders]);

  return null;
}

/** En la web no hay notificaciones nativas (la vista web es solo para probar la interfaz). */
export function NotificationOpener() {
  return Platform.OS === 'web' ? null : <Opener />;
}
