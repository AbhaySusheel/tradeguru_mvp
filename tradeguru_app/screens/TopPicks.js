import React, { useEffect, useState, useCallback } from "react";
import { ScrollView, RefreshControl, View, Text } from "react-native";
import { Card, Button, Title, Paragraph, Chip, useTheme } from "react-native-paper";
import api from "../utils/api";

export default function TopPicks({ onBuy, boughtSymbols = [] }) {
  const { colors } = useTheme();
  const [picks, setPicks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(() => {
    setLoading(true);

    async function fetchTopPicks() {
      try {
        console.log("🔍 Fetching Top Picks from API...");
        const res = await api.getTopPicks(12);
        console.log("✅ API Response:", res);
        setPicks(res?.status === "success" ? res.top_picks || [] : []);
      } catch (err) {
        console.warn("❌ Top picks fetch failed:", err);
        setPicks([]);
      } finally {
        setLoading(false);
      }
    }

    fetchTopPicks();
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      load(); // 2 sec delay to avoid cold start
    }, 2000);
    return () => clearTimeout(timer);
  }, [load]);

  // Add a new useEffect for 2-min auto-refresh
useEffect(() => {
  let prevPicks = [];

  const checkTopPicks = async () => {
    const res = await api.getTopPicks(12);
    if (res?.status !== "success") return;

    const newPicks = res.top_picks || [];
    
    // Compare with previous picks
    newPicks.forEach((stock) => {
      const old = prevPicks.find(s => s.symbol === stock.symbol);
      if (!old) {
        sendNotification(`New Top Pick: ${stock.symbol}`, `Buy confidence: ${stock.buy_confidence.toFixed(2)}%`);
      } else if (stock.buy_confidence > old.buy_confidence) {
        sendNotification(`Updated Top Pick: ${stock.symbol}`, `Buy confidence increased to ${stock.buy_confidence.toFixed(2)}%`);
      }
    });

    prevPicks = newPicks; // Update previous picks
    setPicks(newPicks);
  };

  checkTopPicks(); // initial
  const interval = setInterval(checkTopPicks, 120000); // every 2 min

  return () => clearInterval(interval);
}, []);


  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
    >
      <Title style={{ marginBottom: 16, fontWeight: "800", color: colors.primary }}>
        Top Picks
      </Title>

      {!loading && picks.length === 0 && (
        <Paragraph style={{ opacity: 0.6 }}>No top picks available.</Paragraph>
      )}

      {picks.map((p) => {
        const bought = boughtSymbols.includes(p.symbol);

        return (
          <Card
            key={p.symbol}
            style={{
              marginBottom: 16,
              borderRadius: 16,
              elevation: 3,
              backgroundColor: colors.surface,
            }}
          >
            <Card.Content>
              <View
                style={{
                  flexDirection: "row",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 8,
                }}
              >
                <Title style={{ fontSize: 20, fontWeight: "700" }}>{p.symbol}</Title>

                <View style={{ alignItems: "flex-end" }}>
                  <Text style={{ fontWeight: "700", fontSize: 17, color: colors.primary }}>
                    ₹{p.last_price}
                  </Text>
                  <Chip style={{ marginTop: 6 }}>{Number(p.buy_confidence || 0).toFixed(2)}%</Chip>
                </View>
              </View>

              <Paragraph style={{ marginTop: 8, lineHeight: 20 }}>{p.explanation}</Paragraph>

              <View style={{ flexDirection: "row", marginTop: 12, flexWrap: "wrap" }}>
                {p.trade_plan?.targets?.slice(0, 3).map((t, i) => (
                  <Chip
                    key={i}
                    style={{
                      marginRight: 8,
                      marginTop: 6,
                      backgroundColor: colors.accent + "20", // subtle background
                    }}
                  >
                    T{i + 1}: ₹{Number(t).toFixed(2)}
                  </Chip>
                ))}
              </View>
            </Card.Content>

            <Card.Actions style={{ justifyContent: "flex-end", padding: 12 }}>
              <Button
                mode={bought ? "outlined" : "contained"}
                onPress={() => onBuy(p)}
                disabled={bought}
                style={{ borderRadius: 8 }}
              >
                {bought ? "Bought" : "Buy"}
              </Button>
            </Card.Actions>
          </Card>
        );
      })}
    </ScrollView>
  );
}
