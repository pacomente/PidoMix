import { useLastNotificationResponse } from 'expo-notifications';
import { router } from 'expo-router';
import { useEffect, useRef } from 'react';

import { orderIdFrom } from '@/lib/push';
import { useApp } from '@/state/app-state';

/** Al tocar un aviso de Trappi (con la app abierta, en segundo plano o cerrada) abre ese pedido. */
export function NotificationOpener() {
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
  }, [ready, response, orders]);

  return null;
}
