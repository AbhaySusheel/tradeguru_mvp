import React, { useEffect, useState } from 'react';
import { View, Text, FlatList, RefreshControl } from 'react-native';
import { getSignals } from '../services/api';
import StockCard from '../components/StockCard';

export default function HomeScreen(){
  const [signals, setSignals] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try{
      const res = await getSignals();
      setSignals(res.signals || []);
    }catch(e){ console.log(e); }
  }

  useEffect(()=> { load(); },[])

  return (
    <View style={{flex:1, padding:12}}>
      <Text style={{fontSize:20, fontWeight:'700'}}>Today's Signals</Text>
      <FlatList
        data={signals}
        keyExtractor={(i)=>String(i.id)}
        renderItem={({item})=> <StockCard s={item} /> }
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
      />
    </View>
  )
}
