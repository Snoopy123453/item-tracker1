from product_finder.spec_compare import CandidateComparison, AttributeComparison, create_spec_comparison_workbook


def test_spec_comparison_workbook():
    original={"document_title":"Original","manufacturer":"JOSAM","model":"30000-5A-Z","attributes":[{"category":"Dimensions","attribute":"Top diameter","value":"5","unit":"in","requirement_level":"Required","source_page":"1","evidence":"5 inch top"}]}
    result=CandidateComparison("Candidate","JOSAM","30000-5A-Z","Exact Specification Match",100.0,100.0,0,0,[AttributeComparison("Dimensions","Top diameter","5","5","in","in","Required","Match",1.0,"Same size","1","2")],"Exact")
    name,data=create_spec_comparison_workbook(original,[result])
    assert name.endswith(".xlsx")
    assert len(data)>5000
