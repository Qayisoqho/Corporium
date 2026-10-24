"""The same explicit page sizes for lexemes and shared morphemes."""
SIZES=(10,20,30,50,100,200,500,1000)


def paginate(rows,page=1,page_size=30):
    if str(page_size)=='all':size=max(1,len(rows))
    else:
        try:size=int(page_size)
        except (TypeError,ValueError):raise ValueError('请选择有效的每页条数或全部')
        if size not in SIZES:raise ValueError('每页条数请选择 10、20、30、50、100、200、500、1000 或全部')
    pages=max(1,(len(rows)+size-1)//size);page=max(1,min(int(page),pages))
    return dict(items=rows[(page-1)*size:page*size],total=len(rows),page=page,pages=pages)
