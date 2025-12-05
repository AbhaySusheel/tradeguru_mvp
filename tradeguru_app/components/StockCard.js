import React from "react";
import { View, Text, StyleSheet, TouchableOpacity } from "react-native";

const StockCard = ({ symbol, lastPrice, predictedMax, buyConfidence, onBuy, onSell, isBought }) => {
  // Calculate expected profit % if predictedMax exists
  const profitPct = predictedMax ? (((predictedMax - lastPrice) / lastPrice) * 100).toFixed(2) : "-";

  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <Text style={styles.symbol}>{symbol}</Text>
        <Text style={styles.price}>₹{lastPrice.toFixed(2)}</Text>
      </View>

      <View style={styles.row}>
        <Text style={styles.info}>Max Expected: ₹{predictedMax?.toFixed(2) || "-"}</Text>
        <Text style={styles.info}>Profit %: {profitPct}%</Text>
      </View>

      <View style={styles.row}>
        <Text style={styles.info}>Confidence: {(buyConfidence * 100).toFixed(1)}%</Text>
        {isBought ? (
          <TouchableOpacity style={styles.sellBtn} onPress={onSell}>
            <Text style={styles.btnText}>Sell</Text>
          </TouchableOpacity>
        ) : (
          <TouchableOpacity style={styles.buyBtn} onPress={onBuy}>
            <Text style={styles.btnText}>Buy</Text>
          </TouchableOpacity>
        )}
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
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginVertical: 4,
  },
  symbol: { fontSize: 18, fontWeight: "bold" },
  price: { fontSize: 16, fontWeight: "600" },
  info: { fontSize: 14, color: "#555" },
  buyBtn: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    backgroundColor: "#4CAF50",
    borderRadius: 6,
  },
  sellBtn: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    backgroundColor: "#F44336",
    borderRadius: 6,
  },
  btnText: { color: "#fff", fontWeight: "bold" },
});

export default StockCard;
