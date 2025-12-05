import React, { useEffect, useState } from "react";
import { View, FlatList } from "react-native";
import TransactionCard from "../components/TransactionCard";
import { fetchPositions } from "../services/api";

export default function TransactionsScreen() {
  const [transactions, setTransactions] = useState([]);

  useEffect(() => {
    loadTransactions();
  }, []);

  const loadTransactions = async () => {
    const data = await fetchPositions();
    setTransactions(data); // all positions OPEN + CLOSED
  };

  return (
    <View style={{ flex: 1, padding: 10 }}>
      <FlatList
        data={transactions}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <TransactionCard
            symbol={item.symbol}
            entryPrice={item.entry_price}
            exitPrice={item.sell_price}
            status={item.status}
            createdAt={item.created_at}
            closedAt={item.closed_at}
          />
        )}
      />
    </View>
  );
}
