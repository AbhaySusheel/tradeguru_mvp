import React from "react";
import { ScrollView, TouchableOpacity, View } from "react-native";
import { Card, Title, Paragraph, useTheme } from "react-native-paper";

export default function SoldStocks({ soldStocks = [], navigation }) {
  const { colors } = useTheme();

  return (
    <ScrollView contentContainerStyle={{ padding: 16 }}>
      <Title style={{ marginBottom: 16, color: colors.primary }}>Sold (last 2 days)</Title>

      {soldStocks.length === 0 && (
        <Paragraph style={{ opacity: 0.6 }}>No sold stocks in last 2 days.</Paragraph>
      )}

      {soldStocks.map((s) => (
        <TouchableOpacity
          key={`${s.symbol}-${s.sellTime}`}
          onPress={() => navigation.navigate("StockDetail", { stock: s })}
        >
          <Card
            style={{
              marginBottom: 16,
              borderRadius: 16,
              elevation: 3,
              backgroundColor: colors.surface,
            }}
          >
            <Card.Content>
              <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 8 }}>
                <Title style={{ fontSize: 20, fontWeight: "700" }}>{s.symbol}</Title>
                <Paragraph style={{ fontWeight: "600", color: colors.accent }}>
                  Sold: ₹{s.sellPrice}
                </Paragraph>
              </View>

              <Paragraph>Buy: ₹{s.buyPrice} • {new Date(s.buyTime).toLocaleString()}</Paragraph>
              <Paragraph>Sold: ₹{s.sellPrice} • {new Date(s.sellTime).toLocaleString()}</Paragraph>
            </Card.Content>
          </Card>
        </TouchableOpacity>
      ))}
    </ScrollView>
  );
}
