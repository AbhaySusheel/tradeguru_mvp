import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function HomeScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.heading}>Welcome to TradeGuru</Text>

      <Text style={styles.text}>
        Track markets, view top picks, and review transactions.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#fff'
  },
  heading: {
    fontSize: 26,
    fontWeight: '700',
    marginBottom: 10
  },
  text: {
    fontSize: 16,
    textAlign: 'center',
    maxWidth: 300
  }
});
