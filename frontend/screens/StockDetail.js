import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function StockDetail({ route }) {
  const { stock } = route.params;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{stock.symbol}</Text>
      <Text style={styles.info}>Price: ₹{stock.price.toFixed(2)}</Text>
      <Text style={styles.info}>Change: {stock.change.toFixed(2)}%</Text>
      <Text style={styles.info}>Score: {stock.score?.toFixed(4) ?? 'N/A'}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#fff' },
  title: { fontSize: 24, fontWeight: 'bold', marginBottom: 12 },
  info: { fontSize: 18, marginVertical: 4 },
});
