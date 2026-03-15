function BinPopup({ bin }) {
  const lastEmptied = bin.last_emptied_at ? new Date(bin.last_emptied_at).toLocaleString() : 'Belirlenecek'

  return (
    <div>
      <div className="popup-title">Bin ID: {bin.bin_id}</div>
      <div>State: {bin.status}</div>
      <div>Region: {bin.region}</div>
      <div>Last Emptied: {lastEmptied}</div>
    </div>
  )
}

export default BinPopup
