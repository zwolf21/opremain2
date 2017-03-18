from itertools import groupby
from operator import itemgetter
import sys, os
import xlrd

from db import drugDB


class ExcelParser:

	def __init__(self, xl_path = None, file_content=None, sheet_index=0, **extra_fields):
		wb = xlrd.open_workbook(xl_path) if xl_path else xlrd.open_workbook(file_contents=file_content)
		ws = wb.sheet_by_index(sheet_index)
		fields = ws.row_values(0)
		self._records = [dict(zip(fields, ws.row_values(i))) for i in range(1, ws.nrows)]
		for row in self._records:
			row.update(**extra_fields)

	def __getitem__(self, index):
		return self._records[index]
	
	def __len__(self):
		return len(self._records)

	def __call__(self):
		return self._records

	def select(self, *fields, where=lambda row:row, as_table=False):
		if not fields:
			fields = self._records[0].keys()	
		ret =  [{k:v for k, v in row.items() if k in fields} for row in self._records if where(row)]
		self._records = ret
		if as_table:
			return [list(fields)] + [[row[col] for col in fields] for row in exl]
		return self

	def order_by(self, *rules):
		for rule in reversed(rules):
			rvs = rule.startswith('-')
			rule = rule.strip('-')
			self._records.sort(key=lambda x: x[rule], reverse=rvs)
		return self
			
	def distinct(self, *cols):
		ret = sorted(self._records, key= itemgetter(*cols))
		self._records =  [next(l) for g, l in groupby(ret, key=itemgetter(*cols))]
		return self
	
	def update(self, where=lambda row:row, **set):
		for row in self._records:
			if not where(row):
				continue
			for k, func in set.items():
				row[k] = func(row)
		return self

	def group_by(self, column, **annotates): # annotates: field_name=func
		self._records.sort(key=itemgetter(column))
		ret = []
		for gname, lst in groupby(self._records, key=itemgetter(column)):
			lst = list(lst)
			dic = lst[0]
			for k, func in annotates.items():
				try:
					s = list(map(float, [e[k] for e in lst]))
				except:
					s = [e[k] for e in lst] 
				dic.update({'{}__{}'.format(k, func.__name__): func(s)})
			ret.append(dic)
		return ret

# -------------------------------------------------------------------------------------------------------------------------------------------------
import xlsxwriter

if __name__ == '__main__':
	path_list = []
	exl_table = []
	grp = []
	
	if len(sys.argv) > 1 :
		os.chdir(os.path.dirname(sys.argv[1]))
		for arg in sys.argv:
			fn, ext = os.path.splitext(arg)
			if ext in ['.xls', '.xlsx']:
				path_list.append(arg)

	if not path_list:
		sys.exit(0)


	for n, path in enumerate(path_list):
		exl= ExcelParser(path, 잔량=0, 폐기량=0, 폐기단위='ml', 폐기약품명="") 

		exl = exl.select(where=lambda row: row['불출일자']!="" and row['약품코드'] in drugDB and row['반납구분'] not in ['D/C', '반납'])

		exl.order_by('불출일자','병동')

		exl = exl.update(잔량 = lambda row: float(row['집계량']) - float(row['처방량(규격단위)']))

		exl= exl.update(
			폐기량 = lambda row: round(float(row['잔량']) * drugDB[row['약품코드']]['amount'], 2), 
			폐기단위 = lambda row: drugDB[row['약품코드']]['amount_unit'],
			폐기약품명 = lambda row: drugDB[row['약품코드']]['name'],
		).order_by('약품명','불출일자','병동')
		
		exl = exl.select(where = lambda row: row['폐기량'] >0)
		select_columns = ['불출일자', '병동', '환자번호', '환자명', '폐기약품명', '처방량(규격단위)', '잔량', '규격단위', '폐기량', '폐기단위' ]
		grp += exl.group_by('폐기약품명', 폐기량=sum, 폐기약품명=len)
		exl = exl.select(*select_columns, as_table=True)
		exl_table += exl if n == 0 else exl[1:]


	# -------------------------------------------------------------------------------------------------------------------------------------------------

	date_index = set(row[0] for r, row in enumerate(exl_table) if r >0)
	first_date, last_date = min(date_index), max(date_index)
	title = '{}~{} 마약류 폐기 현황'.format(first_date, last_date)
	fname = '{}.xlsx'.format(title)
	wb = xlsxwriter.Workbook(fname)
	ws = wb.add_worksheet()

	title_format = wb.add_format({'align': 'center', 'bold': True, 'font_size':20})
	float_format = wb.add_format({'num_format': '0.00'})
	ml_format = wb.add_format({'num_format': '0.00 "ml"'})
	mg_format = wb.add_format({'num_format': '0.00 "mg"'})
	g_format = wb.add_format({'num_format': '0.00 "g"'})

	formats = \
	{
		'title': title_format,
		'float': float_format,
		'ml': ml_format,
		'mg': mg_format,
		'g': g_format,
	}

	ws.merge_range(0,0,0, len(exl[0])-2, title, formats['title'])

	ws.set_column('A:A',9)	# 불출일자
	ws.set_column('B:B',3)	# 병동
	ws.set_column('C:C',10)	# 환자번호
	ws.set_column('D:D',6)	# 환자명
	ws.set_column('E:E',20)	# 폐기약품명
	ws.set_column('F:F',5)	# 처방량(규격단위)
	ws.set_column('G:G',5)	# 잔량
	ws.set_column('H:H',5)	# 규격단위
	ws.set_column('I:I',9)	# 폐기량

	for r, row in enumerate(exl_table):
		for c, data in enumerate(row):
			if select_columns[c] == '폐기단위':
				continue

			if select_columns[c] == '폐기량' and r >0:
				ws.write(r+1, c, data, formats[row[-1]])
			elif select_columns[c] == '처방량(규격단위)' and r > 0:
				ws.write(r+1, c, float(data), formats['float'])
			else:
				ws.write(r+1, c, data)

	appen_r = r + 3
	ws.write(appen_r, 3, '종합')
	ws.write(appen_r, 4, '폐기약품명')
	ws.write(appen_r, 5, '')
	ws.write(appen_r, 6, '수량')
	ws.write(appen_r, 7, '규격')
	ws.write(appen_r, 8, '폐기량')
	appen_r +=1
	
	for r, row in enumerate(grp):
		ws.write(appen_r+r, 4, row['폐기약품명'])
		ws.write(appen_r+r, 6, row['폐기약품명__len'])
		ws.write(appen_r+r, 7, row['규격단위'])
		ws.write(appen_r+r, 8, row['폐기량__sum'], formats[drugDB[row['약품코드']]['amount_unit']])


	wb.add_worksheet('보고서')


	wb.close()
	os.startfile(fname)



