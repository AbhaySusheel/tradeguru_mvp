import React, { useEffect, useState } from "react";
import { View, FlatList, Text, Alert } from "react-native";
import StockCard from "../components/StockCard";
import { fetchPositions, sellStock } from "../services/api";

export default function PositionsScreen() {
  const [positions, setPositions] = useState([]);

  useEffect(() => {
    loadPositions();
  }, []);

  const loadPositions = async () => {
    const data = await fetchPositions();
    setPositions(data.filter((p) => p.status === "OPEN"));
  };

  const handleSell = (symbol, entryPrice) => {
    Alert.prompt(
      `Sell ${symbol}`,
      `Enter sell price for ${symbol}`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Sell",
          onPress: async (sellPrice) => {
            if (!sellPrice) return;
            await sellStock(symbol, parseFloat(sellPrice));
            loadPositions();
          },
        },
      ],
      "plain-text",
      entryPrice.toString()
    );
  };

  return (
    <View style={{ flex: 1, padding: 10 }}>
      <FlatList
        data={positions}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <StockCard
            symbol={item.symbol}
            lastPrice={item.entry_price}
            predictedMax={item.predicted_max}
            isBought={true}
            onSell={() => handleSell(item.symbol, item.entry_price)}
          />
        )}
      />
    </View>
  );
}
