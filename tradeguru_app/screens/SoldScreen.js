import React, { useEffect, useState } from "react";
import { View, FlatList, Text } from "react-native";
import StockCard from "../components/StockCard";
import { fetchPositions } from "../services/api";

export default function SoldScreen() {
  const [sold, setSold] = useState([]);

  useEffect(() => {
    loadSold();
  }, []);

  const loadSold = async () => {
    const data = await fetchPositions();
    setSold(data.filter((p) => p.status === "CLOSED"));
  };

  return (
    <View style={{ flex: 1, padding: 10 }}>
      <FlatList
        data={sold}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <StockCard
            symbol={item.symbol}
            lastPrice={item.sell_price}
            predictedMax={item.predicted_max}
            isBought={false}
          />
        )}
      />
    </View>
  );
}
