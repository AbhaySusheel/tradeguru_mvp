import React, { useEffect, useState } from 'react';
import { View, Text, FlatList, TouchableOpacity, ActivityIndicator, StyleSheet, TextInput } from 'react-native';
import axios from 'axios';

const API_BASE = 'https://tradeguru-mvp.onrender.com/api';
const API_KEY = '8f912050f8a403046ea774190bf4fa33';

// ✅ Set global axios header (fix for API key issue)
axios.interceptors.request.use((config) => {
  config.headers["x-api-key"] = API_KEY;
  return config;
});

export default function HomeScreen({ navigation }) {
  const [tab, setTab] = useState('Top Picks');
  const [topPicks, setTopPicks] = useState([]);
  const [allStocks, setAllStocks] = useState([]);
  const [bought, setBought] = useState([]);
  const [sold, setSold] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');

  const fetchAll = async () => {
    try {
      setLoading(true);
      const [tops, all, pos] = await Promise.all([
        axios.get(`${API_BASE}/top-picks`),
        axios.get(`${API_BASE}/all-stocks`),
        axios.get(`${API_BASE}/positions`)
      ]);

      setTopPicks(tops.data || []);
      setAllStocks(all.data || []);
      setBought(pos.data.open || []);
      setSold(pos.data.closed || []);
    } catch (err) {
      console.error('Fetch error:', err.response?.data || err);
      setError('Error connecting to API');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const timer = setInterval(fetchAll, 60000);
    return () => clearInterval(timer);
  }, []);

  // ✅ Buy
  const onBuy = async (stock) => {
    try {
      const payload = { symbol: stock.symbol, buy_price: stock.price };
      await axios.post(`${API_BASE}/positions`, payload);
      alert(`✅ Bought ${stock.symbol} @ ₹${stock.price}`);
      fetchAll();
    } catch (e) {
      console.error('Buy failed', e.response?.data || e);
      alert('Buy failed');
    }
  };

  // ✅ Sell
  const onSell = async (pos) => {
    try {
      const payload = { symbol: pos.symbol, sell_price: pos.current_price || pos.buy_price };
      await axios.post(`${API_BASE}/positions/close`, payload);
      alert(`💰 Sold ${pos.symbol}`);
      fetchAll();
    } catch (e) {
      console.error('Sell failed', e.response?.data || e);
      alert('Sell failed');
    }
  };

  const filteredStocks = allStocks.filter(s =>
    s.symbol.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) return <ActivityIndicator style={{ flex: 1 }} size="large" color="#007bff" />;
  if (error) return <Text style={styles.error}>{error}</Text>;

  const renderStock = (item, showBuy, showSell, showProfit) => (
    <View style={styles.card}>
      <View style={styles.row}>
        <Text style={styles.symbol}>{item.symbol}</Text>
        <Text style={styles.price}>₹{item.price?.toFixed(2)}</Text>
      </View>
      {item.change !== undefined && (
        <Text style={item.change >= 0 ? styles.positive : styles.negative}>
          {item.change >= 0 ? `+${item.change.toFixed(2)}%` : `${item.change.toFixed(2)}%`}
        </Text>
      )}
      {showProfit && item.profit !== undefined && (
        <Text style={item.profit >= 0 ? styles.positive : styles.negative}>
          Profit/Loss: {item.profit.toFixed(2)}%
        </Text>
      )}
      {showBuy && (
        <TouchableOpacity onPress={() => onBuy(item)} style={[styles.smallBtn, { backgroundColor: 'green' }]}>
          <Text style={{ color: 'white' }}>Buy</Text>
        </TouchableOpacity>
      )}
      {showSell && (
        <TouchableOpacity onPress={() => onSell(item)} style={[styles.smallBtn, { backgroundColor: 'red' }]}>
          <Text style={{ color: 'white' }}>Sell</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  const renderList = (data, showBuy, showSell, showProfit = false) => (
    <FlatList
      data={data}
      keyExtractor={(item) => item.symbol}
      renderItem={({ item }) => renderStock(item, showBuy, showSell, showProfit)}
    />
  );

  return (
    <View style={styles.container}>
      {/* Tabs */}
      <View style={styles.tabs}>
        {['All', 'Top Picks', 'Bought', 'Sold'].map((t) => (
          <TouchableOpacity key={t} onPress={() => setTab(t)} style={[styles.tab, tab === t && styles.activeTab]}>
            <Text style={[styles.tabText, tab === t && styles.activeText]}>{t}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Search bar for All Stocks */}
      {tab === 'All' && (
        <TextInput
          placeholder="Search stock..."
          value={search}
          onChangeText={setSearch}
          style={styles.search}
        />
      )}

      {/* Lists */}
      {tab === 'All' && renderList(filteredStocks, false, false)}
      {tab === 'Top Picks' && renderList(topPicks, true, false)}
      {tab === 'Bought' && renderList(bought, false, true)}
      {tab === 'Sold' && renderList(sold, false, false, true)}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 12, backgroundColor: '#fff' },
  card: { padding: 14, borderRadius: 12, backgroundColor: '#f8f9fa', marginBottom: 10, elevation: 2 },
  row: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 5 },
  symbol: { fontSize: 18, fontWeight: 'bold' },
  price: { fontSize: 16 },
  positive: { color: 'green', fontWeight: 'bold' },
  negative: { color: 'red', fontWeight: 'bold' },
  error: { textAlign: 'center', color: 'red', marginTop: 40 },
  tabs: { flexDirection: 'row', justifyContent: 'space-around', marginBottom: 10 },
  tab: { paddingVertical: 6, paddingHorizontal: 10 },
  activeTab: { borderBottomWidth: 2, borderColor: '#007bff' },
  tabText: { fontSize: 16 },
  activeText: { color: '#007bff', fontWeight: 'bold' },
  smallBtn: { marginTop: 6, padding: 6, borderRadius: 8, alignItems: 'center' },
  search: { borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 8, marginBottom: 10 }
});
