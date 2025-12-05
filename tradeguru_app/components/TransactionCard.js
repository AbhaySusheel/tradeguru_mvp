import React from "react";
import { View, Text, StyleSheet } from "react-native";

const TransactionCard = ({ symbol, entryPrice, exitPrice, status, createdAt, closedAt }) => {
  const profitLoss =
    exitPrice && entryPrice ? (exitPrice - entryPrice).toFixed(2) : null;
  const profitLossPct =
    profitLoss && entryPrice ? ((profitLoss / entryPrice) * 100).toFixed(2) : null;

  return (
    <View style={[styles.card, status === "CLOSED" ? styles.closedCard : styles.openCard]}>
      <View style={styles.row}>
        <Text style={styles.symbol}>{symbol}</Text>
        <Text style={styles.status}>{status}</Text>
      </View>

      <View style={styles.row}>
        <Text style={styles.info}>Entry: ₹{entryPrice.toFixed(2)}</Text>
        <Text style={styles.info}>Exit: {exitPrice ? `₹${exitPrice.toFixed(2)}` : "-"}</Text>
      </View>

      {status === "CLOSED" && (
        <View style={styles.row}>
          <Text style={styles.info}>P/L: ₹{profitLoss}</Text>
          <Text style={styles.info}>P/L %: {profitLossPct}%</Text>
        </View>
      )}

      <View style={styles.row}>
        <Text style={styles.info}>Bought: {new Date(createdAt).toLocaleString()}</Text>
        {closedAt && <Text style={styles.info}>Sold: {new Date(closedAt).toLocaleString()}</Text>}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    padding: 15,
    marginVertical: 8,
    marginHorizontal: 16,
    borderRadius: 10,
    backgroundColor: "#fff",
    shadowColor: "#000",
    shadowOpacity: 0.1,
    shadowOffset: { width: 0, height: 2 },
    shadowRadius: 4,
    elevation: 3,
  },
  openCard: { borderLeftWidth: 4, borderLeftColor: "#4CAF50" },
  closedCard: { borderLeftWidth: 4, borderLeftColor: "#F44336" },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginVertical: 4,
  },
  symbol: { fontSize: 18, fontWeight: "bold" },
  status: { fontSize: 14, fontWeight: "600", color: "#555" },
  info: { fontSize: 14, color: "#555" },
});

export default TransactionCard;
