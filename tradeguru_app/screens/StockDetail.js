import React from "react";
import { ScrollView } from "react-native";
import { Card, Title, Paragraph } from "react-native-paper";

export default function StockDetail({ route }) {
  const stock = route.params?.stock;
  if (!stock) return <Paragraph style={{ margin: 12 }}>No stock data.</Paragraph>;

  return (
    <ScrollView contentContainerStyle={{ padding: 12 }}>
      <Card>
        <Card.Content>
          <Title>{stock.symbol}</Title>
          <Paragraph>Buy: ₹{stock.buyPrice} • {new Date(stock.buyTime).toLocaleString()}</Paragraph>
          <Paragraph>Sell: {stock.sellPrice ? `₹${stock.sellPrice} • ${new Date(stock.sellTime).toLocaleString()}` : "—"}</Paragraph>
          {stock.predicted_max && <Paragraph>Estimated max: ₹{stock.predicted_max}</Paragraph>}
          {stock.meta?.explanation && <Paragraph style={{ marginTop: 8 }}>{stock.meta.explanation}</Paragraph>}
        </Card.Content>
      </Card>
    </ScrollView>
  );
}
