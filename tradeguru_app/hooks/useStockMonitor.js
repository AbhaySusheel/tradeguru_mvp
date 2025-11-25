import { useEffect, useRef } from "react";
import * as Notifications from "expo-notifications";
import api from "../utils/api";

export default function useStockMonitor(boughtStocks) {
  const notifiedRef = useRef({});

  useEffect(() => {
    const interval = setInterval(async () => {
      for (let stock of boughtStocks) {
        const latestPrice = await api.getStockPrice(stock.symbol);
        const gain = latestPrice - stock.buyPrice;
        const expectedGain = stock.predicted_max - stock.buyPrice;
        const gainPct = (gain / expectedGain) * 100;

        if (!notifiedRef.current[stock.symbol]) {
          notifiedRef.current[stock.symbol] = { milestones: [] };
        }

        const milestones = [50, 60, 70, 75]; // add intermediate notifications
        for (let m of milestones) {
          if (gainPct >= m && !notifiedRef.current[stock.symbol].milestones.includes(m)) {
            sendNotification(
              `${stock.symbol} is moving up!`,
              `Stock reached ~${m}% of expected gain. Keep monitoring.`
            );
            notifiedRef.current[stock.symbol].milestones.push(m);
          }
        }

        // max reached
        if (latestPrice >= stock.predicted_max && !notifiedRef.current[stock.symbol].milestones.includes("max")) {
          sendNotification(
            `${stock.symbol} reached predicted max!`,
            "Sell now for maximum profit!"
          );
          notifiedRef.current[stock.symbol].milestones.push("max");
        }

        // falling alerts: if price falls after reaching any milestone
        const highestMilestone = Math.max(
          ...notifiedRef.current[stock.symbol].milestones.filter(n => typeof n === "number"),
          0
        );

        if (gainPct < highestMilestone && highestMilestone > 0) {
          sendNotification(
            `${stock.symbol} is dropping!`,
            `Stock is falling after reaching ~${highestMilestone}% gain. Consider selling to secure partial profit.`
          );
          // reset milestones for further monitoring
          notifiedRef.current[stock.symbol].milestones = notifiedRef.current[stock.symbol].milestones.filter(n => n === "max");
        }
      }
    }, 60000); // every 1 minute

    return () => clearInterval(interval);
  }, [boughtStocks]);
}

function sendNotification(title, body) {
  Notifications.scheduleNotificationAsync({
    content: { title, body },
    trigger: null,
  });
}
