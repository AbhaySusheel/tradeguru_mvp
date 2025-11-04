import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function StockCard({ s }){
  return (
    <View style={styles.card}>
      <Text style={styles.ticker}>{s.ticker.replace('.NS','')}</Text>
      <Text>{s.side} • {s.reason}</Text>
      <Text>Entry: {parseFloat(s.entry).toFixed(2)} • SL: {parseFloat(s.sl).toFixed(2)} • Target: {parseFloat(s.target).toFixed(2)}</Text>
      <Text>Confidence: {(s.confidence*100).toFixed(0)}%</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  card: { padding: 12, margin: 8, backgroundColor: '#fff', borderRadius: 8, elevation: 2 },
  ticker: { fontWeight: '700', fontSize: 18 }
});
