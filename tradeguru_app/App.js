import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet, ScrollView } from 'react-native';
import axios from 'axios';
import { Card } from 'react-native-paper';

export default function App() {
  const [status, setStatus] = useState('');
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);

  // Your backend base URL
  const BASE_URL = 'https://tradeguru-mvp.onrender.com';

  useEffect(() => {
    // Fetch API status
    axios.get(`${BASE_URL}/`)
      .then(response => {
        setStatus(response.data.status);
        // Fetch stock data (you can change this route later)
        return axios.get(`${BASE_URL}/stocks`);
      })
      .then(res => {
        setStocks(res.data);
      })
      .catch(err => {
        console.error(err);
        setStatus('Error connecting to API');
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#2196f3" />
        <Text style={styles.text}>Loading TradeGuru...</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.header}>📈 TradeGuru</Text>
      <Text style={styles.status}>API Status: {status}</Text>

      {stocks.length > 0 ? (
        stocks.map((stock, index) => (
          <Card key={index} style={styles.card}>
            <Text style={styles.stockName}>{stock.symbol}</Text>
            <Text>Price: ₹{stock.price}</Text>
            <Text>Change: {stock.change}%</Text>
          </Card>
        ))
      ) : (
        <Text style={styles.text}>No stock data available.</Text>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    backgroundColor: '#f9f9f9',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#fff',
  },
  header: {
    fontSize: 28,
    fontWeight: 'bold',
    marginBottom: 15,
  },
  status: {
    fontSize: 16,
    marginBottom: 20,
  },
  text: {
    fontSize: 16,
    color: '#666',
  },
  card: {
    width: '90%',
    padding: 15,
    marginBottom: 10,
    borderRadius: 10,
    backgroundColor: '#fff',
    elevation: 3,
  },
  stockName: {
    fontSize: 18,
    fontWeight: 'bold',
  },
});
