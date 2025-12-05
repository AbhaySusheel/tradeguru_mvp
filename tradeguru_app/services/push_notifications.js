import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import * as Device from "expo-device";
import { Platform, Alert } from "react-native";
import axios from "axios";

const BASE_URL = "https://tradeguru-mvp.onrender.com";

// Notification handler
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

// Register for push notifications
export async function registerForPushNotificationsAsync() {
  let token;

  if (Device.isDevice) {
    // Get permissions
    const { status: existingStatus } = await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;

    if (existingStatus !== "granted") {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }

    if (finalStatus !== "granted") {
      Alert.alert("Permission required", "Push notifications need permission!");
      return;
    }

    // Ensure projectId retrieval for EAS builds
    const projectId =
      Constants.expoConfig?.extra?.eas?.projectId ??
      Constants.manifest2?.extra?.eas?.projectId;

    // Generate push token
    token = (
      await Notifications.getExpoPushTokenAsync({
        projectId,
      })
    ).data;

    console.log("Expo Push Token:", token);

    // Send to backend
    try {
      await axios.post(`${BASE_URL}/api/register-push-token`, { token });
      console.log("Token registered on backend");
    } catch (err) {
      console.error("Failed to register token on backend", err);
    }
  } else {
    Alert.alert(
      "Physical device required",
      "Push notifications only work on real devices."
    );
  }

  // Android notification channel
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

// Listener for notifications received
export function setupNotificationListener(callback) {
  return Notifications.addNotificationReceivedListener(callback);
}

// Listener for user interactions with notifications
export function setupNotificationResponseListener(callback) {
  return Notifications.addNotificationResponseReceivedListener(callback);
}
