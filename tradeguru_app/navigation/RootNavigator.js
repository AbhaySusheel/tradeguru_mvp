import React, { useEffect } from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { NavigationContainer } from '@react-navigation/native';
import TopPicksScreen from '../screens/TopPicksScreen';
import PositionsScreen from '../screens/PositionsScreen';
import SoldScreen from '../screens/SoldScreen';
import TransactionsScreen from '../screens/TransactionsScreen';
import { 
  registerForPushNotificationsAsync, 
  setupNotificationListener, 
  setupNotificationResponseListener 
} from '../services/push_notifications';

const Tab = createBottomTabNavigator();

export default function RootNavigator() {
  useEffect(() => {
    // Register for push notifications
    registerForPushNotificationsAsync();

    // Setup listeners
    const receivedListener = setupNotificationListener(notification => {
      console.log('Notification received:', notification);
    });

    const responseListener = setupNotificationResponseListener(response => {
      console.log('Notification clicked:', response);
    });

    // Cleanup on unmount
    return () => {
      receivedListener.remove();
      responseListener.remove();
    };
  }, []);

  return (
    <NavigationContainer>
      <Tab.Navigator screenOptions={{ headerShown: true }}>
        <Tab.Screen name="Top Picks" component={TopPicksScreen} />
        <Tab.Screen name="Positions" component={PositionsScreen} />
        <Tab.Screen name="Sold" component={SoldScreen} />
        <Tab.Screen name="Transactions" component={TransactionsScreen} />
      </Tab.Navigator>
    </NavigationContainer>
  );
}
