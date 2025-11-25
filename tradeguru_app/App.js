import React, { useEffect, useState, useRef } from "react";
import { LogBox, Alert, Platform } from "react-native";
import { Provider as PaperProvider, DefaultTheme } from "react-native-paper";
import { NavigationContainer } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createStackNavigator } from "@react-navigation/stack";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Notifications from "expo-notifications";

import api from "./utils/api"; // your backend API wrapper
import TopPicks from "./screens/TopPicks";
import BoughtStocks from "./screens/BoughtStocks";
import SoldStocks from "./screens/SoldStocks";
import Transactions from "./screens/Transactions";
import StockDetail from "./screens/StockDetail";

LogBox.ignoreLogs(["Setting a timer"]); // reduce noise

const Tab = createBottomTabNavigator();
const Stack = createStackNavigator();

const theme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: "#0B69FF",
    accent: "#00C48C",
    background: "#F3F6FA",
    surface: "#FFFFFF",
  },
};

// Notification handler for foreground notifications
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

// Register device for push notifications and send token to backend
async function registerForPushNotificationsAsync() {
  let token;
  try {
    const { status: existingStatus } = await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;

    if (existingStatus !== "granted") {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }

    if (finalStatus !== "granted") {
      Alert.alert("Permission denied", "Failed to get push token!");
      return;
    }

    const tokenData = await Notifications.getExpoPushTokenAsync();
    token = tokenData.data;
    console.log("Expo Push Token:", token);

    // Send token to your backend to store for this user
    await api.registerPushToken(token);
  } catch (e) {
    console.warn("Push notification registration failed", e);
  }

  if (Platform.OS === "android") {
    Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#FF231F7C",
    });
  }

  return token;
}

function SoldStack({ soldStocks, setSoldStocks }) {
  return (
    <Stack.Navigator>
      <Stack.Screen name="SoldMain" options={{ headerShown: false }}>
        {(props) => <SoldStocks {...props} soldStocks={soldStocks} />}
      </Stack.Screen>
      <Stack.Screen
        name="StockDetail"
        component={StockDetail}
        options={{ title: "Stock Detail" }}
      />
    </Stack.Navigator>
  );
}

export default function App() {
  const [bought, setBought] = useState([]);
  const [sold, setSold] = useState([]);
  const [tx, setTx] = useState([]);

  const notificationListener = useRef();
  const responseListener = useRef();
  const navigationRef = useRef();

  useEffect(() => {
    let active = true;

    async function loadStore() {
      try {
        const [b, s, t] = await Promise.all([
          AsyncStorage.getItem("TG_BOUGHT"),
          AsyncStorage.getItem("TG_SOLD"),
          AsyncStorage.getItem("TG_TX"),
        ]);

        if (!active) return;
        if (b) setBought(JSON.parse(b));
        if (s) setSold(JSON.parse(s));
        if (t) setTx(JSON.parse(t));
      } catch (e) {
        console.warn("Load store failed", e);
      }
    }

    loadStore();

    // Register push notifications
    registerForPushNotificationsAsync();

    // Listen for incoming notifications while app is foregrounded
    notificationListener.current = Notifications.addNotificationReceivedListener(
      (notification) => {
        console.log("Notification Received:", notification);
      }
    );

    // Listen for when user interacts with a notification (foreground, background, or closed)
    responseListener.current = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        console.log("Notification Response:", response);

        // If notification contains a stock symbol, navigate to StockDetail
        const symbol = response.notification.request.content.data?.symbol;
        if (symbol && navigationRef.current) {
          navigationRef.current.navigate("Top Picks", {
            screen: "StockDetail",
            params: { symbol },
          });
        }
      }
    );

    return () => {
      active = false;
      Notifications.removeNotificationSubscription(notificationListener.current);
      Notifications.removeNotificationSubscription(responseListener.current);
    };
  }, []);

  useEffect(() => {
    AsyncStorage.setItem("TG_BOUGHT", JSON.stringify(bought));
  }, [bought]);

  useEffect(() => {
    AsyncStorage.setItem("TG_SOLD", JSON.stringify(sold));
  }, [sold]);

  useEffect(() => {
    AsyncStorage.setItem("TG_TX", JSON.stringify(tx));
  }, [tx]);

  const handleBuy = (stock) => {
    const now = new Date().toISOString();
    const rec = {
      symbol: stock.symbol,
      buyPrice: stock.last_price ?? stock.trade_plan?.entry ?? stock.price,
      buyTime: now,
      predicted_max: stock.predicted_max ?? stock.trade_plan?.targets?.slice(-1)?.[0] ?? null,
      meta: stock,
    };
    setBought((p) => [rec, ...p]);
    setTx((t) => [{ ...rec, type: "BUY" }, ...t]);
  };

  const handleSell = (symbol, sellPrice = null) => {
    const idx = bought.findIndex((b) => b.symbol === symbol);
    if (idx === -1) return;
    const pos = bought[idx];
    const now = new Date().toISOString();
    const soldRec = {
      symbol: pos.symbol,
      buyPrice: pos.buyPrice,
      buyTime: pos.buyTime,
      sellPrice: sellPrice ?? pos.buyPrice,
      sellTime: now,
      predicted_max: pos.predicted_max ?? null,
      meta: pos.meta ?? {},
    };

    const nb = [...bought];
    nb.splice(idx, 1);
    setBought(nb);

    setSold((s) => {
      const combined = [soldRec, ...s];
      const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000);
      return combined.filter((x) => new Date(x.sellTime) >= twoDaysAgo);
    });

    setTx((t) => [{ ...soldRec, type: "SELL" }, ...t]);
  };

  return (
    <PaperProvider theme={theme}>
      <NavigationContainer ref={navigationRef}>
        <Tab.Navigator
          screenOptions={({ route }) => ({
            headerShown: false,
            tabBarActiveTintColor: theme.colors.primary,
            tabBarInactiveTintColor: "gray",
            tabBarIcon: ({ color, size }) => {
              const map = {
                "Top Picks": "star-outline",
                "Bought Stocks": "cart-outline",
                "Sold Stocks": "sale",
                Transactions: "history",
              };
              return <MaterialCommunityIcons name={map[route.name]} size={size} color={color} />;
            },
          })}
        >
          <Tab.Screen name="Top Picks">
            {(props) => (
              <TopPicks
                {...props}
                onBuy={handleBuy}
                boughtSymbols={bought.map((b) => b.symbol)}
              />
            )}
          </Tab.Screen>

          <Tab.Screen name="Bought Stocks">
            {(props) => <BoughtStocks {...props} bought={bought} onSell={handleSell} />}
          </Tab.Screen>

          <Tab.Screen name="Sold Stocks">
            {(props) => <SoldStack {...props} soldStocks={sold} setSold={setSold} />}
          </Tab.Screen>

          <Tab.Screen name="Transactions">
            {(props) => <Transactions {...props} transactions={tx} />}
          </Tab.Screen>
        </Tab.Navigator>
      </NavigationContainer>
    </PaperProvider>
  );
}
