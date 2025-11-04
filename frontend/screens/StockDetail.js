import React from 'react';
import { View, Text } from 'react-native';

export default function StockDetail({ route }){
  const { signal } = route.params;
  return (
    <View style={{flex:1, padding:12}}>
      <Text style={{fontSize:22}}>{signal.ticker.replace('.NS','')}</Text>
      <Text>{signal.side}</Text>
      <Text>{signal.reason}</Text>
    </View>
  )
}
