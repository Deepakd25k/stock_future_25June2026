# NSE Sectoral & Stock Futures OI Buildup Scanner

यह प्रोजेक्ट भारतीय शेयर बाजार (NSE) के लाइव डेटा का विश्लेषण कर उन Stock Futures को स्कैन करता है जिनमें **FIIs (Foreign Institutional Investors)** और **Pros (Proprietary Desks)** का पैसा जा रहा है। 

## 🚀 Features

1. **Sectoral Strength Scan**: सभी सेक्टरों को रीयल-टाइम में % Change के आधार पर रैंक करता है ताकि सबसे मजबूत सेक्टर (जैसे Auto, IT) की पहचान हो सके।
2. **Sector Breadth Check**: उस अग्रणी सेक्टर के Advances-Declines (बढ़ने वाले बनाम गिरने वाले स्टॉक्स) की चौड़ाई जांचता है। केवल तभी रिकमेंडेशन देता है जब breadth > 70% हो, जो वास्तविक सेक्टर रोटेशन को दर्शाता है।
3. **F&O OI Buildup Analysis**: NSE से लाइव F&O Open Interest data लेकर प्रत्येक स्टॉक के लिए प्रतिशत OI बदलाव मापता है।
4. **Yahoo Finance Price Tracker**: Akamai bot blocks से बचने के लिए रीयल-टाइम प्राइसिंग Yahoo Finance से डाउनलोड कर OI के साथ मिलाता है।
5. **Buildup Classification**: स्टॉक्स को निम्नलिखित श्रेणियों में बांटता है:
   * **Long Buildup (Price ↑ + OI ↑)**: नए खरीदार बाजार में प्रवेश कर रहे हैं (Directional Buy Trade के लिए सर्वोत्तम)।
   * **Short Buildup (Price ↓ + OI ↑)**: नए बिकवाल बाजार में आ रहे हैं (Short Trade के लिए सर्वोत्तम)।
   * **Short Covering (Price ↑ + OI ↓)**: पुराने बिकवाल पोजीशन काट रहे हैं (कमजोर तेजी)।
   * **Long Unwinding (Price ↓ + OI ↓)**: खरीदार बाहर निकल रहे हैं (कमजोर मंदी)।
6. **Top 2 Stocks**: दिशात्मक ट्रेड (directional trade) के लिए ऑटोमैटिक रूप से शीर्ष 2 स्टॉक्स की सिफारिश करता है।

## 📦 Installation & Setup

1. प्रोजेक्ट क्लोन करें या फाइलें डाउनलोड करें।
2. वर्चुअल एनवायरनमेंट बनाएं और डिपेंडेंसीज इंस्टॉल करें:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## ⚙️ Running the Scanner

स्कैनर चलाने के लिए निम्नलिखित कमांड रन करें:
```bash
python nse_scanner.py
```

## 💡 How it Works (Logic Flow)

1. यह `https://www.nseindia.com/api/allIndices` से लाइव सेक्टर्स की परफॉर्मेंस लेता है।
2. फिर `https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings` से ओपन इंटरेस्ट प्राप्त करता है।
3. `yfinance` का उपयोग कर रीयल-टाइम प्राइस चेंज फेज करता है।
4. दोनों डेटा को कंबाइन कर कंसोल पर एक सुंदर टेबल तथा रेकमेंडेशन्स प्रिंट करता है।
