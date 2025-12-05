import React, { useEffect, useState } from "react";
import { View, FlatList, Text } from "react-native";
import StockCard from "../components/StockCard";
import { fetchTopPicks, buyStock } from "../services/api";

export default function TopPicksScreen() {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadTopPicks();
  }, []);

  const loadTopPicks = async () => {
    setLoading(true);
    const data = await fetchTopPicks();
    setStocks(data);
    setLoading(false);
  };

  const handleBuy = async (symbol, price, predicted_max) => {
    await buyStock(symbol, price, predicted_max);
    alert(`${symbol} bought at ${price}`);
    loadTopPicks();
  };

  return (
    <View style={{ flex: 1, padding: 10 }}>
      {loading && <Text>Loading...</Text>}
      <FlatList
        data={stocks}
        keyExtractor={(item) => item.symbol}
        renderItem={({ item }) => (
          <StockCard
            symbol={item.symbol}
            lastPrice={item.last_price}
            predictedMax={item.predicted_max}
            buyConfidence={item.buy_confidence}
            isBought={false}
            onBuy={() => handleBuy(item.symbol, item.last_price, item.predicted_max)}
          />
        )}
      />
    </View>
  );
}
