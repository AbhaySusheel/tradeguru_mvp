import React from "react";
import { ScrollView, Alert, View } from "react-native";
import { Card, Title, Paragraph, Button, Chip, useTheme } from "react-native-paper";
import useStockMonitor from "../hooks/useStockMonitor";

export default function BoughtStocks({ bought = [], onSell }) {
  const { colors } = useTheme();
  useStockMonitor(bought);

  const confirmSell = (symbol, buyPrice) => {
    Alert.alert(
      "Sell stock",
      `Sell ${symbol} now?`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Sell", style: "destructive", onPress: () => onSell(symbol, buyPrice) },
      ],
      { cancelable: true }
    );
  };

  return (
    <ScrollView contentContainerStyle={{ padding: 16 }}>
      <Title style={{ marginBottom: 16, color: colors.primary }}>Bought Stocks</Title>

      {bought.length === 0 && <Paragraph style={{ opacity: 0.6 }}>No bought stocks yet.</Paragraph>}

      {bought.map((b) => {
        const gainPct = b.predicted_max 
          ? ((b.currentPrice || b.buyPrice) - b.buyPrice) / (b.predicted_max - b.buyPrice) * 100
          : 0;

        return (
          <Card
            key={b.symbol}
            style={{
              marginBottom: 16,
              borderRadius: 16,
              elevation: 3,
              backgroundColor: colors.surface,
            }}
          >
            <Card.Content>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <Title style={{ fontSize: 20, fontWeight: "700" }}>{b.symbol}</Title>
                {b.predicted_max && (
                  <Paragraph style={{ fontWeight: "600", color: colors.accent }}>
                    Predicted max: ₹{b.predicted_max}
                  </Paragraph>
                )}
              </View>

              <Paragraph style={{ marginTop: 8, lineHeight: 20 }}>
                Bought: ₹{b.buyPrice} • {new Date(b.buyTime).toLocaleString()}
              </Paragraph>

              {/* Show gain milestones visually */}
              {b.predicted_max && (
                <View style={{ flexDirection: "row", marginTop: 8, flexWrap: "wrap" }}>
                  {[50, 60, 70, 75, 100].map((milestone) => (
                    <Chip
                      key={milestone}
                      style={{
                        marginRight: 6,
                        marginTop: 6,
                        backgroundColor: gainPct >= milestone ? colors.accent + "40" : colors.accent + "10",
                      }}
                    >
                      {milestone}%
                    </Chip>
                  ))}
                </View>
              )}
            </Card.Content>

            <Card.Actions style={{ justifyContent: "flex-end", padding: 12 }}>
              <Button
                mode="contained"
                onPress={() => confirmSell(b.symbol, b.buyPrice)}
                style={{ borderRadius: 8 }}
              >
                Sell
              </Button>
            </Card.Actions>
          </Card>
        );
      })}
    </ScrollView>
  );
}
