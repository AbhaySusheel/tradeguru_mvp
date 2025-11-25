import React from "react";
import { ScrollView, View } from "react-native";
import { Card, Title, Paragraph, useTheme } from "react-native-paper";

export default function Transactions({ transactions = [] }) {
  const { colors } = useTheme();

  if (!transactions || transactions.length === 0) {
    return <Paragraph style={{ margin: 16, opacity: 0.6 }}>No transactions yet.</Paragraph>;
  }

  return (
    <ScrollView contentContainerStyle={{ padding: 16 }}>
      <Title style={{ marginBottom: 16, color: colors.primary }}>Transactions</Title>

      {transactions.map((tx, idx) => (
        <Card
          key={`${tx.symbol}-${idx}`}
          style={{
            marginBottom: 16,
            borderRadius: 16,
            elevation: 3,
            backgroundColor: colors.surface,
          }}
        >
          <Card.Content>
            <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 6 }}>
              <Title style={{ fontSize: 18, fontWeight: "700" }}>{tx.symbol}</Title>
              <Paragraph style={{ fontWeight: "600", color: tx.type === "BUY" ? colors.accent : colors.primary }}>
                {tx.type}
              </Paragraph>
            </View>

            <Paragraph>Price: ₹{tx.type === "BUY" ? tx.buyPrice : tx.sellPrice}</Paragraph>
            <Paragraph>Time: {new Date(tx.type === "BUY" ? tx.buyTime : tx.sellTime).toLocaleString()}</Paragraph>
            {tx.predicted_max && <Paragraph>Predicted Max: ₹{tx.predicted_max}</Paragraph>}
          </Card.Content>
        </Card>
      ))}
    </ScrollView>
  );
}
